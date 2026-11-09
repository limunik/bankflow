UPDATE bank.accounts SET status = 'blocked', updated_at = now()
WHERE account_id = (SELECT account_id FROM bank.accounts WHERE status = 'active' ORDER BY account_id LIMIT 1)
RETURNING account_id, status, updated_at;
