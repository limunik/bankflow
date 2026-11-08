import logging
import traceback
from bankflow_lib import repository
LOG = logging.getLogger(__name__)

def load_table(get_connection, source, ds, run_id, attempt):
    log_id = repository.log_start(get_connection, f'dds_{source}', ds, 'dds', run_id, attempt)
    try:
        counts = repository.call_dds_function(get_connection, source, ds)
        LOG.info('%-12s прочитано %s, новых версий %s, изменено %s', source, counts['src_rows'], counts['inserted'], counts['updated'])
    except Exception as error:
        repository.log_finish(get_connection, log_id, 'failed', 0, f'{error}\n{traceback.format_exc()}'[:2000])
        raise
    repository.log_finish(get_connection, log_id, 'success', counts['inserted'] + counts['updated'], None)
    return counts
