"""Пул клиентов, счетов и карт.

Строится ДЕТЕРМИНИРОВАННО (одинаково при каждом запуске) от SEED.
Иерархия, как в логической модели: клиент 1:N счёт, счёт 1:N карта.
Клиент бывает физическим или юридическим лицом (customer_type).
У каждой карты есть платёжная система (VISA или MASTERCARD).

Для переводов у каждого клиента есть:
    trusted  доверенные получатели (счета, куда он переводит регулярно);
             у физлица это родные, арендодатель; у юрлица поставщики;
    payroll  зарплатная ведомость (только у юрлица): счета сотрудников.

У каждого счёта есть состояние (active, blocked, closed). Неактивные счета получают
дату, с которой они неактивны (inactive_from). Эти же данные потом становятся
начальной выгрузкой таблицы accounts в oltp (см. build_accounts).
"""
import random
from datetime import date, datetime, timedelta, timezone

import config


def choose_scheme(rng, owned):
    """Выбирает платёжную систему для новой карты.

    owned: список систем, которые у клиента уже есть (в порядке выпуска).
    С вероятностью OTHER_SCHEME_PROB берём систему, отличную от предыдущей карты.
    """
    if owned and rng.random() < config.OTHER_SCHEME_PROB:
        other = [s for s in config.CARD_SCHEMES if s != owned[-1]]
        return rng.choice(other)
    return rng.choices(list(config.CARD_SCHEMES), list(config.CARD_SCHEMES.values()))[0]


def _assign_account_states(cards):
    """Раздаёт счетам статусы и даты блокировки (отдельный генератор, SEED + 2).

    Дата блокировки выбирается так, чтобы после неё в периоде оставалось не меньше 10 дней.
    """
    rng = random.Random(config.SEED + 2)
    span = (config.PERIOD_END - config.PERIOD_START).days - 10
    states = {}
    for card in cards:
        acc = card["account_id"]
        if acc not in states:                 # состояние решаем один раз на счёт
            r = rng.random()
            if r < config.BLOCKED_SHARE:
                status = "blocked"
            elif r < config.BLOCKED_SHARE + config.CLOSED_SHARE:
                status = "closed"
            else:
                status = "active"
            changed = None
            if status != "active":
                changed = config.PERIOD_START + timedelta(days=rng.randint(0, span))
            states[acc] = (status, changed)
        card["account_status"], card["inactive_from"] = states[acc]


def _assign_relationships(cards):
    """Доверенные получатели (trusted) и зарплатные ведомости (payroll). Генератор SEED + 4."""
    rng = random.Random(config.SEED + 4)

    accounts_of = {}    # клиент -> его счета
    ctype = {}          # клиент -> тип
    for c in cards:
        accs = accounts_of.setdefault(c["customer_id"], [])
        if c["account_id"] not in accs:
            accs.append(c["account_id"])
        ctype[c["customer_id"]] = c["customer_type"]

    indiv_accounts = [a for cu, accs in accounts_of.items()
                      if ctype[cu] == "individual" for a in accs]
    legal_accounts = [a for cu, accs in accounts_of.items()
                      if ctype[cu] == "legal" for a in accs]

    relations = {}
    for cust, accs in accounts_of.items():
        own = set(accs)
        k = rng.randint(*config.TRUSTED_PER_CUSTOMER)
        if ctype[cust] == "individual":
            # sample берём с запасом: свои счета отфильтруем
            trusted = [a for a in rng.sample(indiv_accounts, k + 4) if a not in own][:k]
            payroll = []
        else:
            trusted = [a for a in rng.sample(legal_accounts, min(k + 4, len(legal_accounts)))
                       if a not in own][:k]
            payroll = rng.sample(indiv_accounts, rng.randint(*config.PAYROLL_SIZE))
        relations[cust] = (trusted, payroll)

    for c in cards:
        c["trusted"], c["payroll"] = relations[c["customer_id"]]


def build_card_pool():
    """Создаёт список всех карт банка. Каждая карта это словарь:

        card_id, account_id, customer_id   идентификаторы
        customer_type   individual (физлицо) или legal (юрлицо)
        card_scheme     VISA или MASTERCARD
        scale           «масштаб трат» клиента (у юрлица в LEGAL_SCALE_MULT раз больше)
        weight          «активность» карты: чем больше, тем чаще по ней операции
        apple_pay, qr   пользуется ли клиент способом оплаты
        account_status, inactive_from   состояние счёта в начальной выгрузке
        trusted, payroll                доверенные получатели и зарплатная ведомость
    """
    rng = random.Random(config.SEED)

    cards = []
    account_n = 0
    card_n = 0

    for c in range(1, config.N_CUSTOMERS + 1):
        customer_id = f"CL{c:05d}"

        is_legal = rng.random() < config.SHARE_LEGAL
        customer_type = "legal" if is_legal else "individual"

        scale = rng.lognormvariate(0, 0.5)      # масштаб трат клиента
        activity = rng.lognormvariate(0, 0.7)   # насколько часто он платит
        if is_legal:
            scale *= config.LEGAL_SCALE_MULT
            activity *= config.LEGAL_ACTIVITY_MULT

        apple_pay = rng.random() < config.SHARE_APPLE_PAY_USERS
        qr = rng.random() < config.SHARE_QR_USERS

        owned_schemes = []

        if is_legal:
            n_accounts = rng.randint(1, 3)
        else:
            n_accounts = 2 if rng.random() < 0.5 else 1

        for _ in range(n_accounts):
            account_n += 1
            account_id = f"AC{account_n:06d}"

            if is_legal:
                n_cards = rng.randint(1, 3)
            else:
                n_cards = rng.choices(list(config.CARDS_PER_ACCOUNT),
                                      list(config.CARDS_PER_ACCOUNT.values()))[0]

            for _ in range(n_cards):
                card_n += 1
                scheme = choose_scheme(rng, owned_schemes)
                owned_schemes.append(scheme)

                cards.append({
                    "card_id": f"CD{card_n:06d}",
                    "account_id": account_id,
                    "customer_id": customer_id,
                    "customer_type": customer_type,
                    "card_scheme": scheme,
                    "scale": scale,
                    "weight": activity * rng.uniform(0.5, 1.5),
                    "apple_pay": apple_pay,
                    "qr": qr,
                })

    _assign_account_states(cards)
    _assign_relationships(cards)
    return cards


def build_accounts(cards):
    """Начальная выгрузка таблицы accounts: по одной строке на счёт.

    Поля: account_id, customer_id, status, balance, limit_amount, opened_at, updated_at.
    updated_at у неактивного счёта = момент блокировки или закрытия.
    """
    rng = random.Random(config.SEED + 3)
    accounts = {}
    for card in cards:
        acc = card["account_id"]
        if acc in accounts:
            continue
        status = card["account_status"]
        changed = card["inactive_from"]

        limit_amount = rng.choice([50000, 100000, 200000, 500000])
        if card["customer_type"] == "legal":
            limit_amount *= 10                      # у юрлица лимиты выше
        balance = 0.0 if status == "closed" else round(limit_amount * rng.uniform(0.05, 0.9), 2)
        opened_at = date(2019, 1, 1) + timedelta(days=rng.randint(0, 2000))

        if changed is not None:
            updated_at = datetime(changed.year, changed.month, changed.day,
                                  rng.randint(0, 23), rng.randint(0, 59), tzinfo=timezone.utc)
        else:
            updated_at = datetime(opened_at.year, opened_at.month, opened_at.day,
                                  tzinfo=timezone.utc)

        accounts[acc] = {
            "account_id": acc,
            "customer_id": card["customer_id"],
            "status": status,
            "balance": balance,
            "limit_amount": limit_amount,
            "opened_at": opened_at,
            "updated_at": updated_at,
        }
    return list(accounts.values())
