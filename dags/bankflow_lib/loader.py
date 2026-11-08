import csv
import logging
from pathlib import Path
from bankflow_lib import repository
from bankflow_lib.config import DATA_DIR, SOURCE_COLUMNS, SOURCE_FILES, STG_TABLES
LOG = logging.getLogger(__name__)

def source_path(source, ds, data_dir=DATA_DIR):
    return Path(data_dir) / SOURCE_FILES[source].format(ds=ds)

def read_header(path):
    with open(path, newline='', encoding='utf-8') as f:
        return next(csv.reader(f))

def _copy_into(cursor, path, columns):
    sql = f"COPY tmp_load ({', '.join(columns)}) FROM STDIN WITH (FORMAT csv, HEADER true)"
    if hasattr(cursor, 'copy_expert'):
        with open(path, encoding='utf-8', newline='') as f:
            cursor.copy_expert(sql, f)
    else:
        with open(path, 'rb') as f, cursor.copy(sql) as copy:
            while (chunk := f.read(1 << 20)):
                copy.write(chunk)

def copy_file(get_connection, source, ds, path):
    meta = STG_TABLES[source]
    columns = SOURCE_COLUMNS[source]
    header = read_header(path)
    if header != columns:
        raise ValueError(f'Заголовок файла {path.name} не совпадает с ожидаемым: {header}')
    col_list = ', '.join(columns)
    col_defs = ', '.join((f'{c} text' for c in columns))
    lock_key = f"{meta['table']}:{ds}" if meta['by_ds'] else meta['table']
    with repository.transaction(get_connection) as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', (lock_key,))
        if meta['by_ds']:
            cursor.execute(f"DELETE FROM {meta['table']} WHERE _ds = %s", (ds,))
        else:
            cursor.execute(f"DELETE FROM {meta['table']}")
        cursor.execute(f'CREATE TEMP TABLE tmp_load ({col_defs}) ON COMMIT DROP')
        _copy_into(cursor, path, columns)
        cursor.execute(f"INSERT INTO {meta['table']} ({col_list}, _ds, _source) SELECT {col_list}, %s, %s FROM tmp_load", (ds, path.name))
        return cursor.rowcount

def load_source(get_connection, source, ds, run_id, attempt, data_dir=DATA_DIR):
    path = source_path(source, ds, data_dir)
    log_id = repository.log_start(get_connection, source, ds, 'stg', run_id, attempt)
    try:
        if not path.exists():
            raise FileNotFoundError(f'Файл не найден: {path}')
        rows = copy_file(get_connection, source, ds, path)
        repository.log_finish(get_connection, log_id, 'success', rows, None)
        LOG.info('%s за %s: загружено %s строк из %s', source, ds, rows, path.name)
        return rows
    except Exception as exc:
        repository.log_finish(get_connection, log_id, 'failed', 0, str(exc)[:2000])
        raise
