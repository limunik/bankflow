select
    rate_date as ds,
    rate
from {{ source('ods', 'ods_fx_rates') }}
where currency = 'USD'
