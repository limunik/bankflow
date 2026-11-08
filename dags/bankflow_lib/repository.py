from contextlib import closing, contextmanager
from bankflow_lib.config import DATAMART_FUNCTIONS, DDS_FUNCTIONS, ODS_FUNCTIONS, ODS_TABLES, STG_TABLES

@contextmanager
def transaction(get_connection):
    with closing(get_connection()) as connection:
        connection.autocommit = False
        try:
            with connection.cursor() as cursor:
                yield cursor
            connection.commit()
        except Exception:
            connection.rollback()
            raise

def stg_rows(get_connection, source, ds):
    meta = STG_TABLES[source]
    with transaction(get_connection) as cursor:
        if meta['by_ds']:
            cursor.execute(f"SELECT count(*) FROM {meta['table']} WHERE _ds = %s", (ds,))
        else:
            cursor.execute(f"SELECT count(*) FROM {meta['table']}")
        return cursor.fetchone()[0]

def last_load_status(get_connection, ds):
    with transaction(get_connection) as cursor:
        cursor.execute('SELECT source, status, rows_loaded FROM stg.etl_load_log WHERE ds = %s ORDER BY id DESC LIMIT 5', (ds,))
        return cursor.fetchall()

def log_start(get_connection, source, ds, layer, run_id, attempt):
    with closing(get_connection()) as connection:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO stg.etl_load_log (source, ds, started_at, status, layer, run_id, attempt) VALUES (%s, %s, now(), 'running', %s, %s, %s) RETURNING id", (source, ds, layer, run_id, attempt))
            return cursor.fetchone()[0]

def log_finish(get_connection, log_id, status, rows, error, rows_rejected=None):
    with closing(get_connection()) as connection:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute('UPDATE stg.etl_load_log SET finished_at = now(), status = %s, rows_loaded = %s, error_message = %s,     rows_rejected = %s WHERE id = %s', (status, rows, error, rows_rejected, log_id))

def call_ods_function(get_connection, source, ds, max_reject_share=None):
    function = ODS_FUNCTIONS[source]
    with transaction(get_connection) as cursor:
        cursor.execute(f'SELECT * FROM {function}(%s::date)', (ds,))
        stg_rows, duplicates, rejected, inserted, updated = cursor.fetchone()
        share = rejected / stg_rows if stg_rows else 0
        if max_reject_share is not None and share > max_reject_share:
            raise ValueError(f'{source}: отбраковано {share:.1%} строк (порог {max_reject_share:.0%}), загрузка отменена; смотрите ods.ods_reject за {ds}')
    return {'stg_rows': stg_rows, 'duplicates': duplicates, 'rejected': rejected, 'inserted': inserted, 'updated': updated}

def ods_rows(get_connection, source, ds):
    meta = ODS_TABLES[source]
    with transaction(get_connection) as cursor:
        if meta['date_column']:
            cursor.execute(f"SELECT count(*) FROM {meta['table']} WHERE {meta['date_column']} = %s", (ds,))
        else:
            cursor.execute(f"SELECT count(*) FROM {meta['table']}")
        return cursor.fetchone()[0]

def call_dds_function(get_connection, source, ds):
    function = DDS_FUNCTIONS[source]
    with transaction(get_connection) as cursor:
        cursor.execute(f'SELECT * FROM {function}(%s::date)', (ds,))
        src_rows, inserted, updated = cursor.fetchone()
    return {'src_rows': src_rows, 'inserted': inserted, 'updated': updated}

def run_quality_checks(get_connection, ds, layers=None):
    with transaction(get_connection) as cursor:
        cursor.execute('SELECT layer, check_name, severity, status, failed_rows, details FROM dq.run_checks(%s::date, %s)', (ds, layers))
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def call_datamart_function(get_connection, source, ds):
    function = DATAMART_FUNCTIONS[source]
    with transaction(get_connection) as cursor:
        cursor.execute(f"SELECT * FROM {function}(%s::date)", (ds,))
        src_rows, inserted, updated = cursor.fetchone()
    return {"src_rows": src_rows, "inserted": inserted, "updated": updated}
