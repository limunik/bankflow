\copy (SELECT account_id, customer_id, status, balance, limit_amount, opened_at, updated_at FROM bank.accounts ORDER BY account_id) TO STDOUT WITH CSV
