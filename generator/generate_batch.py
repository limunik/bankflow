"""Генератор батчей BankFlow: merchants.csv, cards.csv, transactions_ДАТА.csv и ground_truth_ДАТА.csv.

Батч = «пачка» данных за один период (у нас за один день).

Запуск (из корня проекта):
    docker compose run --rm generator python generate_batch.py --start 2026-07-31 --days 91

Порядок работы:
    1. Создаём справочник мерчантов (или читаем, если файл уже есть).
    2. Строим пул карт и записываем справочник cards.csv.
    3. Для каждой даты:
         а) генерируем обычные операции (зарплаты, вечерние пики, суммы по категориям);
         б) добавляем сценарии фрода и «похожие на фрод» законные операции;
         в) записываем файл ground_truth (правильные ответы для оценки правил);
         г) портим ~1% строк (дубли, пропуски) и записываем transactions_ДАТА.csv.
ground_truth пайплайн НЕ читает: он нужен только для оценки качества правил.
"""
import argparse            # разбор параметров командной строки
import csv                 # чтение и запись CSV-файлов
import os                  # файлы и переменные окружения
import random              # генератор случайных чисел
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

from faker import Faker    # придумывает правдоподобные названия компаний

import config
from pool import build_card_pool

# ---------------------------------------------------------------------------
# Пути к файлам
# ---------------------------------------------------------------------------
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))

MERCHANTS_FILE = DATA_DIR / "merchants" / "merchants.csv"
CARDS_FILE = DATA_DIR / "cards" / "cards.csv"
TX_DIR = DATA_DIR / "transactions"
GT_DIR = DATA_DIR / "ground_truth"

MERCHANT_COLUMNS = ["merchant_id", "merchant_name", "category", "country"]
CARD_COLUMNS = ["card_id", "account_id", "customer_id", "card_scheme"]
TX_COLUMNS = [
    "transaction_id", "card_id", "account_id", "customer_id",
    "merchant_id", "transaction_ts", "amount", "currency", "channel",
    "payment_method",
]
# ground_truth: только операции из сценариев. Обычные операции в файл не попадают
# (для них is_fraud = 0 по умолчанию).
GT_COLUMNS = ["transaction_id", "is_fraud", "scenario", "scenario_id", "scenario_start_ts"]

ONLINE_CATEGORIES = {"Онлайн-покупки", "Путешествия"}
BIG_CATEGORIES = {"Электроника", "Путешествия", "Одежда"}   # где бывают крупные покупки
MARKET_CATEGORIES = {"Продукты", "Транспорт"}               # где бывают серии мелких покупок


def write_csv(path, columns, rows):
    """Записывает список словарей `rows` в CSV-файл `path`.

    Пишем во ВРЕМЕННЫЙ файл (.tmp) и переименовываем в настоящий: переименование
    мгновенное и целиком, поэтому сенсор Airflow никогда не увидит
    наполовину записанный файл.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)


def generate_merchants():
    """Создаёт справочник мерчантов и записывает merchants.csv."""
    rng = random.Random(config.SEED + 1)

    fake = Faker("ru_RU")
    fake.seed_instance(config.SEED)

    cats = list(config.CATEGORIES)
    cat_weights = [config.CATEGORIES[c][1] for c in cats]
    countries = list(config.COUNTRIES)
    country_weights = list(config.COUNTRIES.values())

    rows = []
    for i in range(1, config.N_MERCHANTS + 1):
        rows.append({
            "merchant_id": f"M{i:05d}",
            "merchant_name": fake.company(),
            "category": rng.choices(cats, cat_weights)[0],
            "country": rng.choices(countries, country_weights)[0],
        })

    write_csv(MERCHANTS_FILE, MERCHANT_COLUMNS, rows)
    return rows


def generate_cards(cards):
    """Записывает справочник карт cards.csv. Служебные поля генератора в файл не попадают."""
    rows = [{k: c[k] for k in CARD_COLUMNS} for c in cards]
    write_csv(CARDS_FILE, CARD_COLUMNS, rows)
    return rows


def load_merchants():
    with open(MERCHANTS_FILE, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def day_factor(d):
    """Во сколько раз операций в день `d` больше обычного.

    Выходные: +15%. День зарплаты (5-е и 20-е): в 1.6 раза больше.
    Следующий день после зарплаты: в 1.3 раза больше. Множители перемножаются.
    """
    factor = 1.0
    if d.weekday() >= 5:
        factor *= 1.15
    if d.day in config.SALARY_DAYS:
        factor *= 1.6
    elif (d - timedelta(days=1)).day in config.SALARY_DAYS:
        factor *= 1.3
    return factor


def pick(rng, weights_dict):
    """Выбирает один ключ словаря с учётом весов."""
    return rng.choices(list(weights_dict), list(weights_dict.values()))[0]


def make_row(rng, card, merchant, ts, amount_kgs, channel=None):
    """Собирает одну операцию (без transaction_id: он появится после сортировки).

    amount_kgs: сумма в сомах; в валюту операции переводим по примерному курсу.
    channel: если не задан, выбирается по категории мерчанта.
    """
    cur_mix = (config.CURRENCY_DOMESTIC if merchant["country"] == "KG"
               else config.CURRENCY_FOREIGN)
    currency = pick(rng, cur_mix)
    amount = max(round(amount_kgs / config.APPROX_RATE_TO_KGS[currency], 2), 0.5)

    if channel is None:
        if merchant["category"] in ONLINE_CATEGORIES:
            channel = "ONLINE"
        else:
            channel = rng.choices(["POS", "ONLINE"], [85, 15])[0]

    # Способ оплаты зависит от канала и от привычек клиента
    pm_mix = dict(config.PAYMENT_METHOD_POS if channel == "POS"
                  else config.PAYMENT_METHOD_ONLINE)
    if not card["apple_pay"]:
        pm_mix.pop("APPLE_PAY", None)
    if not card["qr"] or merchant["country"] != "KG":
        pm_mix.pop("QR", None)           # QR: только у «qr-клиентов» и только внутри страны
    payment_method = pick(rng, pm_mix)

    return {
        "card_id": card["card_id"],
        "account_id": card["account_id"],
        "customer_id": card["customer_id"],
        "merchant_id": merchant["merchant_id"],
        "transaction_ts": ts.strftime("%Y-%m-%d %H:%M:%S"),
        "amount": f"{amount:.2f}",
        "currency": currency,
        "channel": channel,
        "payment_method": payment_method,
    }


# ---------------------------------------------------------------------------
# Сценарии. Каждая функция возвращает список троек (операция, название, is_fraud).
# Все серии укладываются в ОДНУ календарную минуту (секунда начала = 0), чтобы
# правило «5 операций за минуту» сработало при любой реализации окна.
# ---------------------------------------------------------------------------
def rand_ts(rng, d, second=None):
    """Случайное время в течение дня. Час не больше 21, чтобы сценарии не вылезали за полночь."""
    return datetime(d.year, d.month, d.day, rng.randrange(0, 22),
                    rng.randrange(0, 59), rng.randrange(60) if second is None else second)


def typical_kgs(rng, card):
    """Обычная для клиента сумма в сомах."""
    return card["scale"] * config.TYPICAL_MEDIAN_KGS * rng.lognormvariate(0, 0.6)


def big_kgs(rng, card, low, high):
    """Сумма в low..high раз больше «обычного» чека клиента."""
    return card["scale"] * config.TYPICAL_MEDIAN_KGS * rng.uniform(low, high)


def sc_series(rng, d, ctx, big):
    """Фрод: серия 5-8 мелких онлайн-списаний за минуту. При big=True ещё и крупное в конце."""
    card = rng.choice(ctx["active_cards"])
    t0 = rand_ts(rng, d, second=0)
    merchants = [rng.choice(ctx["kg_online"]) for _ in range(rng.randint(1, 3))]
    offsets = sorted(rng.randrange(0, 50) for _ in range(rng.randint(5, 8)))
    out = []
    for off in offsets:
        row = make_row(rng, card, rng.choice(merchants), t0 + timedelta(seconds=off),
                       rng.uniform(50, 400), "ONLINE")
        out.append((row, "series_big" if big else "series", 1))
    if big:
        row = make_row(rng, card, rng.choice(merchants),
                       t0 + timedelta(seconds=rng.randint(52, 58)),
                       big_kgs(rng, card, 8, 20), "ONLINE")
        out.append((row, "series_big", 1))
    return out


def sc_big_amount(rng, d, ctx):
    """Фрод: одна крупная операция, в 8-20 раз больше обычного чека клиента."""
    card = rng.choice(ctx["active_cards"])
    row = make_row(rng, card, rng.choice(ctx["kg_big"]), rand_ts(rng, d),
                   big_kgs(rng, card, 8, 20))
    return [(row, "big_amount", 1)]


def sc_two_countries(rng, d, ctx):
    """Фрод: оплата дома, а через 5-50 минут по той же карте в другой стране (на терминале)."""
    card = rng.choice(ctx["active_cards"])
    t0 = rand_ts(rng, d)
    leg1 = make_row(rng, card, rng.choice(ctx["kg"]), t0, typical_kgs(rng, card), "POS")
    leg2 = make_row(rng, card, rng.choice(ctx["foreign"]),
                    t0 + timedelta(minutes=rng.randint(5, 50)), typical_kgs(rng, card), "POS")
    # Первая операция законная (это настоящий владелец), мошенническая вторая.
    return [(leg1, "two_countries_leg1", 0), (leg2, "two_countries", 1)]


def sc_inactive(rng, d, ctx):
    """Фрод: 1-3 операции по счёту, который уже заблокирован или закрыт."""
    card = rng.choice(ctx["dead_cards"])
    t0 = rand_ts(rng, d)
    merchant = rng.choice(ctx["kg"])
    out = []
    for i in range(rng.randint(1, 3)):
        ts = t0 + timedelta(minutes=i * rng.randint(2, 15))
        out.append((make_row(rng, card, merchant, ts, typical_kgs(rng, card)),
                    "inactive_account", 1))
    return out


def sc_legit_burst(rng, d, ctx):
    """Законно, но похоже на фрод: 5-7 мелких покупок за минуту на рынке (оплата по очереди)."""
    card = rng.choice(ctx["active_cards"])
    t0 = rand_ts(rng, d, second=0)
    merchant = rng.choice(ctx["kg_market"])
    offsets = sorted(rng.randrange(0, 55) for _ in range(rng.randint(5, 7)))
    return [(make_row(rng, card, merchant, t0 + timedelta(seconds=off),
                      rng.uniform(30, 300), "POS"), "legit_burst", 0) for off in offsets]


def sc_legit_big(rng, d, ctx):
    """Законно, но похоже на фрод: крупная покупка (ноутбук, билеты), в 5.5-9 раз больше обычного."""
    card = rng.choice(ctx["active_cards"])
    row = make_row(rng, card, rng.choice(ctx["kg_big"]), rand_ts(rng, d),
                   big_kgs(rng, card, 5.5, 9))
    return [(row, "legit_big_purchase", 0)]


def sc_legit_foreign_online(rng, d, ctx):
    """Законно, но похоже на фрод: покупка дома, а через 10-50 минут онлайн-заказ у зарубежного магазина."""
    card = rng.choice(ctx["active_cards"])
    t0 = rand_ts(rng, d)
    leg1 = make_row(rng, card, rng.choice(ctx["kg"]), t0, typical_kgs(rng, card), "POS")
    leg2 = make_row(rng, card, rng.choice(ctx["foreign"]),
                    t0 + timedelta(minutes=rng.randint(10, 50)), typical_kgs(rng, card), "ONLINE")
    return [(leg1, "legit_foreign_online_leg1", 0), (leg2, "legit_foreign_online", 0)]


SCENARIOS = {
    "series": lambda rng, d, ctx: sc_series(rng, d, ctx, big=False),
    "series_big": lambda rng, d, ctx: sc_series(rng, d, ctx, big=True),
    "big_amount": sc_big_amount,
    "two_countries": sc_two_countries,
    "inactive_account": sc_inactive,
    "legit_burst": sc_legit_burst,
    "legit_big_purchase": sc_legit_big,
    "legit_foreign_online": sc_legit_foreign_online,
}


def generate_transactions(d, cards, merchants, dirty_rate):
    """Создаёт операции за дату `d`, записывает файлы и возвращает (строки, грязь, ground_truth)."""
    # Свой генератор случайных чисел НА КАЖДУЮ ДАТУ: файл за дату всегда одинаковый.
    rng = random.Random(f"{config.SEED}-{d.isoformat()}")

    # Кто может платить в этот день. Счёт, который блокируется в день X, платит
    # обычными операциями только ДО X; после X по нему остаются лишь попытки мошенников.
    eligible = [c for c in cards if c["inactive_from"] is None or d < c["inactive_from"]]
    dead = [c for c in cards if c["inactive_from"] is not None and d > c["inactive_from"]]

    n = int(config.BASE_TX_PER_DAY * day_factor(d) * rng.uniform(0.95, 1.05))

    card_weights = [c["weight"] for c in eligible]
    merchant_weights = [config.CATEGORIES[m["category"]][1] for m in merchants]
    chosen_cards = rng.choices(eligible, card_weights, k=n)
    chosen_merchants = rng.choices(merchants, merchant_weights, k=n)
    hours = rng.choices(range(24), config.HOUR_WEIGHTS, k=n)

    rows = []
    for i in range(n):
        card = chosen_cards[i]
        merchant = chosen_merchants[i]
        ts = datetime(d.year, d.month, d.day, hours[i], rng.randrange(60), rng.randrange(60))
        median_kgs = config.CATEGORIES[merchant["category"]][0]
        amount_kgs = median_kgs * card["scale"] * rng.lognormvariate(0, 0.6)
        rows.append(make_row(rng, card, merchant, ts, amount_kgs))

    # ----- Сценарии -----
    ctx = {
        "active_cards": eligible,
        "dead_cards": dead,
        "kg": [m for m in merchants if m["country"] == "KG"],
        "foreign": [m for m in merchants if m["country"] != "KG"],
        "kg_online": [m for m in merchants
                      if m["country"] == "KG" and m["category"] in ONLINE_CATEGORIES],
        "kg_big": [m for m in merchants
                   if m["country"] == "KG" and m["category"] in BIG_CATEGORIES],
        "kg_market": [m for m in merchants
                      if m["country"] == "KG" and m["category"] in MARKET_CATEGORIES],
    }
    k = 0
    for name, count in config.SCENARIOS_PER_DAY.items():
        for _ in range(count):
            if name == "inactive_account" and not dead:
                continue
            triples = SCENARIOS[name](rng, d, ctx)
            k += 1
            scenario_id = f"S{d:%Y%m%d}{k:04d}"
            fraud_ts = [r["transaction_ts"] for r, _, fr in triples if fr]
            start_ts = min(fraud_ts) if fraud_ts else min(r["transaction_ts"] for r, _, _ in triples)
            for row, label, is_fraud in triples:
                row["_gt"] = (label, is_fraud, scenario_id, start_ts)   # метка, снимем ниже
                rows.append(row)

    # Сортируем по времени и присваиваем номера: T + дата + порядковый номер
    rows.sort(key=lambda r: r["transaction_ts"])
    for i, row in enumerate(rows, start=1):
        row["transaction_id"] = f"T{d:%Y%m%d}{i:06d}"

    # ground_truth: собираем метки и убираем их из операций
    gt = []
    for row in rows:
        meta = row.pop("_gt", None)
        if meta:
            label, is_fraud, scenario_id, start_ts = meta
            gt.append({"transaction_id": row["transaction_id"], "is_fraud": is_fraud,
                       "scenario": label, "scenario_id": scenario_id,
                       "scenario_start_ts": start_ts})
    write_csv(GT_DIR / f"ground_truth_{d.isoformat()}.csv", GT_COLUMNS, gt)

    # «Грязные» данные (после ground_truth: метки хранят правду об исходной операции)
    dirty = Counter()
    extra = []
    for row in rows:
        if rng.random() < dirty_rate:
            kind = rng.choice(["duplicate", "empty_merchant", "empty_amount"])
            if kind == "duplicate":
                extra.append(dict(row))
            elif kind == "empty_merchant":
                row["merchant_id"] = ""
            else:
                row["amount"] = ""
            dirty[kind] += 1

    rows = sorted(rows + extra, key=lambda r: r["transaction_ts"])
    write_csv(TX_DIR / f"transactions_{d.isoformat()}.csv", TX_COLUMNS, rows)
    return rows, dirty, gt


def summarize(d, rows, dirty, gt):
    n = len(rows)
    hours = [int(r["transaction_ts"][11:13]) for r in rows]
    night = sum(h < 6 for h in hours) / n
    evening = sum(18 <= h <= 21 for h in hours) / n
    cur = Counter(r["currency"] for r in rows)
    pm = Counter(r["payment_method"] for r in rows)
    fraud = sum(1 for g in gt if g["is_fraud"] == 1)
    look = sum(1 for g in gt if g["is_fraud"] == 0)

    print(
        f"{d} | строк: {n:5d} | ночь: {night:5.1%} | вечер: {evening:5.1%} | "
        f"KGS/USD/EUR: {cur['KGS']}/{cur['USD']}/{cur['EUR']} | "
        f"CARD/QR/APPLE: {pm['CARD']}/{pm['QR']}/{pm['APPLE_PAY']} | "
        f"фрод: {fraud} | сценарии-не-фрод: {look} | грязных: {sum(dirty.values())}"
    )


def main():
    parser = argparse.ArgumentParser(description="Генератор батчей BankFlow")
    parser.add_argument("--start", required=True, help="первая дата, YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=1, help="сколько дат подряд")
    parser.add_argument("--dirty-rate", type=float, default=config.DIRTY_RATE,
                        help="доля грязных строк, 0..1")
    parser.add_argument("--regen-merchants", action="store_true",
                        help="пересоздать merchants.csv")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)

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
        rows, dirty, gt = generate_transactions(d, cards, merchants, args.dirty_rate)
        summarize(d, rows, dirty, gt)


if __name__ == "__main__":
    main()
