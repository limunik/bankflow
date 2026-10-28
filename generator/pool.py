
import random

import config


def build_card_pool():
    rng = random.Random(config.SEED)
    cards = []
    account_n = 0
    card_n = 0

    for c in range(1, config.N_CUSTOMERS + 1):
        customer_id = f"CL{c:05d}"
        scale = rng.lognormvariate(0, 0.5)     # «масштаб трат» клиента
        activity = rng.lognormvariate(0, 0.7)  # насколько часто он платит

        n_accounts = 2 if rng.random() < 0.5 else 1
        for _ in range(n_accounts):
            account_n += 1
            account_id = f"AC{account_n:06d}"

            n_cards = 2 if rng.random() < 0.3 else 1
            for _ in range(n_cards):
                card_n += 1
                cards.append({
                    "card_id": f"CD{card_n:06d}",
                    "account_id": account_id,
                    "customer_id": customer_id,
                    "scale": scale,
                    "weight": activity * rng.uniform(0.5, 1.5),
                })
    return cards