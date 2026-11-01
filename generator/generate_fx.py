"""Генератор курсов валют: fx_rates_ДАТА.csv (USD и EUR к сому).

Курс «блуждает» от стартового значения из config.FX_START: каждый день небольшой
случайный шаг плюс притяжение обратно к старту, чтобы отклонение было плавным
и не уходило дальше ±6%. Курс на любую дату считается от FX_BASE_DATE по одним и тем же
случайным шагам, поэтому он воспроизводим и не зависит от порядка запуска дат.

Запуск (из корня проекта):
    docker compose run --rm generator python generate_fx.py --start 2026-07-31 --days 91
"""
import argparse
import random
from datetime import date, timedelta

import config
from generate_batch import DATA_DIR, write_csv   # те же правила записи файлов

FX_DIR = DATA_DIR / "fx_rates"
FX_COLUMNS = ["rate_date", "currency", "rate"]


def rate_on(currency, d):
    """Курс валюты к сому на дату d (сомов за 1 единицу валюты)."""
    start = config.FX_START[currency]
    low = start * (1 - config.FX_MAX_DEVIATION)
    high = start * (1 + config.FX_MAX_DEVIATION)

    rate = start
    day = config.FX_BASE_DATE
    while day <= d:
        # Шаг этого дня зависит только от валюты и даты: результат воспроизводим
        rng = random.Random(f"{config.SEED}-fx-{currency}-{day.isoformat()}")
        rate += config.FX_REVERSION * (start - rate) \
            + rng.gauss(0, config.FX_DAILY_VOLATILITY) * start
        rate = min(max(rate, low), high)   # не выходим за границы ±6%
        day += timedelta(days=1)
    return round(rate, 4)


def main():
    parser = argparse.ArgumentParser(description="Генератор курсов валют")
    parser.add_argument("--start", required=True, help="первая дата, YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=1, help="сколько дат подряд")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    for k in range(args.days):
        d = start + timedelta(days=k)
        rows = [
            {"rate_date": d.isoformat(), "currency": cur, "rate": f"{rate_on(cur, d):.4f}"}
            for cur in config.FX_START
        ]
        write_csv(FX_DIR / f"fx_rates_{d.isoformat()}.csv", FX_COLUMNS, rows)
        print(f"{d} | " + " | ".join(f"{r['currency']}: {r['rate']}" for r in rows))


if __name__ == "__main__":
    main()
