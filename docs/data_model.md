# Модель данных BankFlow

## Слои хранилища (Postgres dwh)

| Схема | Назначение | Ключевые таблицы |
| --- | --- | --- |
| stg | Данные как пришли, журнал загрузок | stg_transactions, stg_merchants, stg_cards, stg_customers, stg_fx_rates, stg_accounts_cdc, etl_load_log |
| ods | Типы, ключи, без дублей, брак отдельно | ods_transactions, ods_merchants, ods_cards, ods_customers, ods_fx_rates, ods_accounts, ods_reject |
| dds | Core: измерения, факт, антифрод | см. ER-диаграмму er_core.png |
| datamart | Витрины для отчётов | dm_transactions_daily, dm_category_monthly |
| dq | Проверки качества как данные | check_def, check_result |
| eval | Эталон фрода и оценка правил | ground_truth |
| dbt | Результат сборки dbt | dm_transactions_daily_dbt |

## Core (dds)

Факт `dds_fact_transaction`: одна строка на операцию. Суррогатные ключи измерений: клиент, карта, мерчант, дата. Сумма хранится в валюте операции и в сомах (`amount_kgs` = `amount` × `fx_rate`). Ограничение `ck_fact_type`: покупка всегда с мерчантом и без получателя, перевод всегда с получателем и без мерчанта.

| Измерение | Тип истории | Бизнес-ключ | Как хранится история |
| --- | --- | --- | --- |
| dds_dim_customer | SCD2 | customer_id | valid_from, valid_to (даты), is_current, запрет пересечения периодов |
| dds_dim_account | SCD2 | account_id | valid_from, valid_to (время), is_current, запрет пересечения периодов |
| dds_dim_merchant | SCD1 | merchant_id | перезапись, _updated_at |
| dds_dim_card | SCD1 | card_id | перезапись, _updated_at |
| dds_dim_date | справочник | date_key | 2026–2027, признак is_payday (5-е и 20-е) |

Интервалы полуоткрытые: `[valid_from, valid_to)`. Открытая версия имеет `valid_to` = 9999-12-31.

Связь факта со счётом идёт по `account_id` без внешнего ключа: у счёта несколько версий, а операция берёт ту, что действовала в момент операции.

## Антифрод

| Таблица | Что хранит |
| --- | --- |
| dds_rule | Правила и их баллы (inactive_account 60, two_countries 50, series 40, new_recipient_big 40, anomalous_amount 30, trusted_recipient −20) |
| dds_decision_level | Границы решений: allow от 0, confirm от 30, suspicious от 50 |
| dds_transaction_flag | Какие правила сработали на операции и сколько баллов дали |
| dds_transaction_score | Сумма баллов и решение по операции |

`ground_truth` лежит только в схеме eval и пайплайном не читается.

## Идемпотентность

| Слой | Приём |
| --- | --- |
| stg | перезагрузка за дату |
| ods | DELETE + INSERT за дату в одной транзакции под advisory lock; брак выше 5% отменяет загрузку |
| dds | upsert с WHERE IS DISTINCT FROM; SCD2 с запретом пересечений |
| datamart | DELETE + INSERT за дату |
| CDC | уникальность (topic, partition, offset); обновление ods_accounts только если source_lsn новее |
| ClickHouse | удаление строки за дату и вставка, затем сверка с Postgres |
