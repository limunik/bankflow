@'

\# Паспорт датасета BankFlow



| Источник | Файл / таблица | Роль | Зерно |

|---|---|---|---|

| Операции по картам | transactions\_YYYY-MM-DD.csv | событие с датой | одна операция |

| Справочник мерчантов | merchants.csv | справочник | один мерчант |

| Курсы валют | fx\_rates\_YYYY-MM-DD.csv | сгенерированный курс USD и EUR к KGS на дату | валюта x дата |

| Счета | oltp.accounts (Postgres) | источник CDC | один счёт |

'@ | Set-Content docs\\dataset\_passport.md -Encoding utf8



