"""Генератор батчей BankFlow: merchants.csv, cards.csv и transactions_YYYY-MM-DD.csv.

Батч = «пачка» данных за один период (у нас за один день).

Запуск (из корня проекта):
    docker compose run --rm generator python generate_batch.py --start 2026-10-01 --days 10

Порядок работы:
    1. Создаём справочник мерчантов (или читаем, если файл уже есть).
    2. Строим пул карт и записываем справочник cards.csv.
    3. Для каждой даты: генерируем операции, добавляем «грязные» строки,
       записываем файл transactions_ДАТА.csv.
"""
import argparse            # разбор параметров командной строки (--start, --days)
import csv                 # чтение и запись CSV-файлов
import os                  # файлы и переменные окружения
import random              # генератор случайных чисел
from collections import Counter     # счётчик: сколько раз встретилось каждое значение
from datetime import date, datetime, timedelta   # даты, время и сдвиг на N дней
from pathlib import Path   # удобная работа с путями

from faker import Faker    # придумывает правдоподобные названия компаний

import config                          # наши настройки
from pool import build_card_pool       # функция построения пула карт

# ---------------------------------------------------------------------------
# Пути к файлам
# ---------------------------------------------------------------------------
# Корневая папка данных берётся из переменной окружения DATA_DIR (в Docker это /data)
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))

MERCHANTS_FILE = DATA_DIR / "merchants" / "merchants.csv"
CARDS_FILE = DATA_DIR / "cards" / "cards.csv"
TX_DIR = DATA_DIR / "transactions"

# Названия колонок в том порядке, в котором они будут в файлах.
# Они же станут колонками таблиц stg.
MERCHANT_COLUMNS = ["merchant_id", "merchant_name", "category", "country"]
CARD_COLUMNS = ["card_id", "account_id", "customer_id", "card_scheme"]
TX_COLUMNS = [
    "transaction_id", "card_id", "account_id", "customer_id",
    "merchant_id", "transaction_ts", "amount", "currency", "channel",
    "payment_method",
]

# Категории, где оплата почти всегда онлайн
ONLINE_CATEGORIES = {"Онлайн-покупки", "Путешествия"}


def write_csv(path, columns, rows):
    """Записывает список словарей `rows` в CSV-файл `path`.

    Пишем во ВРЕМЕННЫЙ файл (.tmp) и переименовываем в настоящий: переименование
    мгновенное и целиком, поэтому сенсор Airflow (день 8) никогда не увидит
    наполовину записанный файл.
    """
    path.parent.mkdir(parents=True, exist_ok=True)   # создаём папку, если её нет
    tmp = Path(str(path) + ".tmp")

    # newline="" нужен модулю csv (иначе на Windows появятся пустые строки);
    # encoding="utf-8" сохраняет кириллицу
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()     # первая строка: названия колонок
        writer.writerows(rows)   # остальные строки

    os.replace(tmp, path)   # переименование tmp в path (заменяет старый файл)


def generate_merchants():
    """Создаёт справочник мерчантов и записывает merchants.csv."""
    # +1 к seed: мерчанты и операции используют РАЗНЫЕ последовательности случайных чисел
    rng = random.Random(config.SEED + 1)

    fake = Faker("ru_RU")              # названия компаний в русском стиле
    fake.seed_instance(config.SEED)    # фиксируем случайность Faker: названия всегда одинаковые

    # Из словарей настроек делаем списки названий и весов (формат для rng.choices)
    cats = list(config.CATEGORIES)
    cat_weights = [config.CATEGORIES[c][1] for c in cats]
    countries = list(config.COUNTRIES)
    country_weights = list(config.COUNTRIES.values())

    rows = []
    for i in range(1, config.N_MERCHANTS + 1):
        rows.append({
            "merchant_id": f"M{i:05d}",
            "merchant_name": fake.company(),
            # choices возвращает список из одного элемента, берём [0]
            "category": rng.choices(cats, cat_weights)[0],
            "country": rng.choices(countries, country_weights)[0],
        })

    write_csv(MERCHANTS_FILE, MERCHANT_COLUMNS, rows)
    return rows


def generate_cards(cards):
    """Записывает справочник карт cards.csv из пула карт.

    В файл попадают только справочные поля. Служебные (масштаб трат, привычки
    способов оплаты) нужны только генератору и в данные не выгружаются.
    """
    rows = [
        {
            "card_id": c["card_id"],
            "account_id": c["account_id"],
            "customer_id": c["customer_id"],
            "card_scheme": c["card_scheme"],
        }
        for c in cards
    ]
    write_csv(CARDS_FILE, CARD_COLUMNS, rows)
    return rows


def load_merchants():
    """Читает готовый merchants.csv и возвращает список словарей."""
    with open(MERCHANTS_FILE, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def day_factor(d):
    """Во сколько раз операций в день `d` больше обычного.

    Выходные: +15%. День зарплаты (5-е и 20-е): в 1.6 раза больше.
    Следующий день после зарплаты: в 1.3 раза больше. Множители перемножаются.
    """
    factor = 1.0

    if d.weekday() >= 5:             # суббота (5) и воскресенье (6)
        factor *= 1.15

    if d.day in config.SALARY_DAYS:
        factor *= 1.6
    # elif: «день после зарплаты» проверяем, только если сегодня НЕ день зарплаты
    elif (d - timedelta(days=1)).day in config.SALARY_DAYS:
        factor *= 1.3

    return factor


def pick(rng, weights_dict):
    """Выбирает один ключ словаря с учётом весов.

    Пример: pick(rng, {"KGS": 98, "USD": 2}) вернёт "KGS" в ~98 случаях из 100.
    """
    return rng.choices(list(weights_dict), list(weights_dict.values()))[0]


def generate_transactions(d, cards, merchants, dirty_rate):
    """Создаёт операции за дату `d`, записывает файл и возвращает (строки, статистику грязи)."""
    # Свой генератор случайных чисел НА КАЖДУЮ ДАТУ: seed + дата в виде текста.
    # Файл за одну и ту же дату всегда одинаковый, а порядок запуска дат не влияет.
    rng = random.Random(f"{config.SEED}-{d.isoformat()}")

    # Сколько операций в этот день: база * поправка дня * небольшой случайный разброс (±5%)
    n = int(config.BASE_TX_PER_DAY * day_factor(d) * rng.uniform(0.95, 1.05))

    # Веса: активные карты платят чаще, популярные категории встречаются чаще
    card_weights = [c["weight"] for c in cards]
    merchant_weights = [config.CATEGORIES[m["category"]][1] for m in merchants]

    # Сразу выбираем n карт, n мерчантов и n часов («с возвращением»: одна карта может встретиться много раз)
    chosen_cards = rng.choices(cards, card_weights, k=n)
    chosen_merchants = rng.choices(merchants, merchant_weights, k=n)
    hours = rng.choices(range(24), config.HOUR_WEIGHTS, k=n)   # вечерний пик через веса часов

    rows = []
    for i in range(n):
        card = chosen_cards[i]
        merchant = chosen_merchants[i]

        # Время: выбранный час + случайные минуты и секунды
        ts = datetime(d.year, d.month, d.day, hours[i],
                      rng.randrange(60), rng.randrange(60))

        # Валюта зависит от страны мерчанта
        cur_mix = (config.CURRENCY_DOMESTIC if merchant["country"] == "KG"
                   else config.CURRENCY_FOREIGN)
        currency = pick(rng, cur_mix)

        # Сумма в KGS: медианный чек категории * масштаб трат клиента * лог-нормальный множитель.
        # Так суммы реалистичны: много небольших чеков и редкие крупные.
        median_kgs = config.CATEGORIES[merchant["category"]][0]
        amount_kgs = median_kgs * card["scale"] * rng.lognormvariate(0, 0.6)

        # Переводим в валюту операции по примерному курсу, округляем до копеек
        amount = max(round(amount_kgs / config.APPROX_RATE_TO_KGS[currency], 2), 0.5)

        # Канал: ONLINE (интернет) или POS (терминал в магазине)
        if merchant["category"] in ONLINE_CATEGORIES:
            channel = "ONLINE"
        else:
            channel = rng.choices(["POS", "ONLINE"], [85, 15])[0]

        # Способ оплаты зависит от канала и от привычек клиента
        pm_mix = dict(config.PAYMENT_METHOD_POS if channel == "POS"
                      else config.PAYMENT_METHOD_ONLINE)
        if not card["apple_pay"]:
            pm_mix.pop("APPLE_PAY", None)    # у клиента нет Apple Pay
        if not card["qr"] or merchant["country"] != "KG":
            pm_mix.pop("QR", None)           # QR: только у «qr-клиентов» и только внутри страны
        payment_method = pick(rng, pm_mix)

        rows.append({
            "card_id": card["card_id"],
            "account_id": card["account_id"],
            "customer_id": card["customer_id"],
            "merchant_id": merchant["merchant_id"],
            "transaction_ts": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "amount": f"{amount:.2f}",
            "currency": currency,
            "channel": channel,
            "payment_method": payment_method,
        })

    # Сортируем по времени, как в жизни
    rows.sort(key=lambda r: r["transaction_ts"])

    # Номер операции присваиваем ПОСЛЕ сортировки: T + дата + порядковый номер
    for i, row in enumerate(rows, start=1):
        row["transaction_id"] = f"T{d:%Y%m%d}{i:06d}"

    # «Грязные» данные: в реальности всегда бывают дубли и пропуски.
    # stg хранит их как есть, ods их почистит.
    dirty = Counter()   # сколько грязных строк каждого вида
    extra = []          # сюда складываем дубли

    for row in rows:
        if rng.random() < dirty_rate:
            kind = rng.choice(["duplicate", "empty_merchant", "empty_amount"])
            if kind == "duplicate":
                extra.append(dict(row))      # точная копия строки (с тем же transaction_id)
            elif kind == "empty_merchant":
                row["merchant_id"] = ""      # пропуск: не указан мерчант
            else:
                row["amount"] = ""           # пропуск: не указана сумма
            dirty[kind] += 1

    rows = sorted(rows + extra, key=lambda r: r["transaction_ts"])

    write_csv(TX_DIR / f"transactions_{d.isoformat()}.csv", TX_COLUMNS, rows)
    return rows, dirty


def summarize(d, rows, dirty):
    """Печатает строку статистики по дню, чтобы сразу видеть, что данные правдоподобны."""
    n = len(rows)

    # Из "2026-10-01 18:45:07" символы 11-12 это час
    hours = [int(r["transaction_ts"][11:13]) for r in rows]
    night = sum(h < 6 for h in hours) / n               # доля ночных (00-05)
    evening = sum(18 <= h <= 21 for h in hours) / n     # доля вечерних (18-21)

    cur = Counter(r["currency"] for r in rows)
    pm = Counter(r["payment_method"] for r in rows)

    print(
        f"{d} | строк: {n:5d} | ночь: {night:5.1%} | вечер: {evening:5.1%} | "
        f"KGS/USD/EUR: {cur['KGS']}/{cur['USD']}/{cur['EUR']} | "
        f"CARD/QR/APPLE: {pm['CARD']}/{pm['QR']}/{pm['APPLE_PAY']} | "
        f"грязных: {dict(dirty)}"
    )


def main():
    """Точка входа: разбирает параметры и запускает генерацию."""
    parser = argparse.ArgumentParser(description="Генератор батчей BankFlow")
    parser.add_argument("--start", required=True, help="первая дата, YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=1, help="сколько дат подряд")
    parser.add_argument("--dirty-rate", type=float, default=config.DIRTY_RATE,
                        help="доля грязных строк, 0..1")
    parser.add_argument("--regen-merchants", action="store_true",
                        help="пересоздать merchants.csv")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)

    # Справочник мерчантов один на все даты: создаём, только если его нет
    if args.regen_merchants or not MERCHANTS_FILE.exists():
        merchants = generate_merchants()
        print(f"merchants.csv создан: {len(merchants)} строк")
    else:
        merchants = load_merchants()
        print(f"merchants.csv уже есть: {len(merchants)} строк (не трогаем)")

    cards = build_card_pool()
    generate_cards(cards)
    print(f"cards.csv создан: {len(cards)} строк")

    for k in range(args.days):
        d = start + timedelta(days=k)
        rows, dirty = generate_transactions(d, cards, merchants, args.dirty_rate)
        summarize(d, rows, dirty)


if __name__ == "__main__":
    main()