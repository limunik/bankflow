import argparse
import csv
import os
import random 
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

from faker import Faker

import config
from pool import build_card_pool

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
MERCHANTS_FILE = DATA_DIR / "merchants"/ "merchants.csv"
TX_DIR = DATA_DIR / "transactions"

MERCHANT_COLUMNS = ["merchant_id", "merchant_name", "category", "country"]
TX_COLUMNS = [
    "transaction_id", "card_id", "account_id", "customer_id",
    "merchant_id", "transaction_ts", "amount", "currency", "channel",
]
ONLINE_CATEGORIES = {"Онлайн-покупки", "Путешествия"}

def write_csv(path, columns, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)

def generate_merchants():
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


def load_merchants():
    with open(MERCHANTS_FILE, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def day_factor(d):
    """Во сколько раз операций больше обычного: выходные и зарплатные дни."""
    factor = 1.0
    if d.weekday() >= 5:
        factor *= 1.15
    if d.day in config.SALARY_DAYS:
        factor *= 1.6
    elif (d - timedelta(days=1)).day in config.SALARY_DAYS:
        factor *= 1.3
    return factor


def pick(rng, weights_dict):
    return rng.choices(list(weights_dict), list(weights_dict.values()))[0]


def generate_transactions(d, cards, merchants, dirty_rate):
    # Свой генератор случайных чисел на каждую дату: файл за дату всегда одинаков
    rng = random.Random(f"{config.SEED}-{d.isoformat()}")

    n = int(config.BASE_TX_PER_DAY * day_factor(d) * rng.uniform(0.95, 1.05))

    card_weights = [c["weight"] for c in cards]
    merchant_weights = [config.CATEGORIES[m["category"]][1] for m in merchants]
    chosen_cards = rng.choices(cards, card_weights, k=n)
    chosen_merchants = rng.choices(merchants, merchant_weights, k=n)
    hours = rng.choices(range(24), config.HOUR_WEIGHTS, k=n)

    rows = []
    for i in range(n):
        card = chosen_cards[i]
        merchant = chosen_merchants[i]

        ts = datetime(d.year, d.month, d.day, hours[i],
                      rng.randrange(60), rng.randrange(60))

        mix = (config.CURRENCY_DOMESTIC if merchant["country"] == "KG"
               else config.CURRENCY_FOREIGN)
        currency = pick(rng, mix)

        median_kgs = config.CATEGORIES[merchant["category"]][0]
        amount_kgs = median_kgs * card["scale"] * rng.lognormvariate(0, 0.6)
        amount = max(round(amount_kgs / config.APPROX_RATE_TO_KGS[currency], 2), 0.5)

        if merchant["category"] in ONLINE_CATEGORIES:
            channel = "ONLINE"
        else:
            channel = rng.choices(["POS", "ONLINE"], [85, 15])[0]

        rows.append({
            "card_id": card["card_id"],
            "account_id": card["account_id"],
            "customer_id": card["customer_id"],
            "merchant_id": merchant["merchant_id"],
            "transaction_ts": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "amount": f"{amount:.2f}",
            "currency": currency,
            "channel": channel,
        })

    # Номера операций по возрастанию времени: T + дата + порядковый номер
    rows.sort(key=lambda r: r["transaction_ts"])
    for i, row in enumerate(rows, start=1):
        row["transaction_id"] = f"T{d:%Y%m%d}{i:06d}"

    # «Грязные» строки: дубли и пропуски
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
    return rows, dirty


def summarize(d, rows, dirty):
    n = len(rows)
    hours = [int(r["transaction_ts"][11:13]) for r in rows]
    night = sum(h < 6 for h in hours) / n
    evening = sum(18 <= h <= 21 for h in hours) / n
    cur = Counter(r["currency"] for r in rows)
    print(
        f"{d} | строк: {n:5d} | ночь 00-05: {night:5.1%} | вечер 18-21: {evening:5.1%} | "
        f"KGS/USD/EUR: {cur['KGS']}/{cur['USD']}/{cur['EUR']} | грязных: {dict(dirty)}"
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
    print(f"Пул карт: {len(cards)}")

    for k in range(args.days):
        d = start + timedelta(days=k)
        rows, dirty = generate_transactions(d, cards, merchants, args.dirty_rate)
        summarize(d, rows, dirty)


if __name__ == "__main__":
    main()