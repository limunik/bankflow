"""Пул карт: клиенты, счета и карты.

Строится ДЕТЕРМИНИРОВАННО (одинаково при каждом запуске) от SEED.
Иерархия, как в логической модели: клиент 1:N счёт, счёт 1:N карта.
У каждой карты есть платёжная система (VISA или MASTERCARD).
Привычки способов оплаты (Apple Pay, QR) задаются на клиента.
"""
import random

import config


def choose_scheme(rng, owned):
    """Выбирает платёжную систему для новой карты.

    owned: список систем, которые у клиента уже есть (в порядке выпуска).
    С вероятностью OTHER_SCHEME_PROB берём систему, отличную от предыдущей карты,
    иначе выбираем по весам из конфига.
    """
    if owned and rng.random() < config.OTHER_SCHEME_PROB:
        # список систем, кроме той, что у последней карты клиента
        other = [s for s in config.CARD_SCHEMES if s != owned[-1]]
        return rng.choice(other)
    return rng.choices(list(config.CARD_SCHEMES), list(config.CARD_SCHEMES.values()))[0]


def build_card_pool():
    """Создаёт список всех карт банка. Каждая карта это словарь:

        card_id      номер карты (CD000001...)
        account_id   счёт, к которому привязана карта (AC000001...)
        customer_id  клиент-владелец (CL00001...)
        card_scheme  платёжная система: VISA или MASTERCARD
        scale        «масштаб трат» клиента (1.0 = средний)
        weight       «активность» карты: чем больше, тем чаще по ней операции
        apple_pay    True, если клиент пользуется Apple Pay
        qr           True, если клиент платит по QR
    """
    # Свой генератор случайных чисел с нашим seed: результат всегда одинаковый
    rng = random.Random(config.SEED)

    cards = []
    account_n = 0   # сквозной счётчик счетов
    card_n = 0      # сквозной счётчик карт

    for c in range(1, config.N_CUSTOMERS + 1):
        customer_id = f"CL{c:05d}"   # {c:05d}: число, дополненное нулями до 5 знаков

        # Лог-нормальное распределение: у большинства значения около 1,
        # у немногих намного больше. Так выглядят реальные траты.
        scale = rng.lognormvariate(0, 0.5)      # масштаб трат клиента
        activity = rng.lognormvariate(0, 0.7)   # насколько часто он платит

        # Привычки клиента: пользуется ли он Apple Pay и QR
        apple_pay = rng.random() < config.SHARE_APPLE_PAY_USERS
        qr = rng.random() < config.SHARE_QR_USERS

        owned_schemes = []   # платёжные системы, уже выпущенные этому клиенту

        n_accounts = 2 if rng.random() < 0.5 else 1
        for _ in range(n_accounts):
            account_n += 1
            account_id = f"AC{account_n:06d}"

            # От 1 до 3 карт на счёт (веса из конфига)
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
                    "card_scheme": scheme,
                    "scale": scale,   # один на клиента: все его карты тратят «в его стиле»
                    "weight": activity * rng.uniform(0.5, 1.5),
                    "apple_pay": apple_pay,
                    "qr": qr,
                })
    return cards