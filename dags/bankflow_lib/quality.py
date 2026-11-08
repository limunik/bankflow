import logging
import traceback
from bankflow_lib import repository
from bankflow_lib.config import DQ_FAIL_SEVERITY
LOG = logging.getLogger(__name__)

class QualityError(Exception):
    pass

def run(get_connection, ds, run_id, attempt, layers=None):
    log_id = repository.log_start(get_connection, 'quality', ds, 'dq', run_id, attempt)
    try:
        results = repository.run_quality_checks(get_connection, ds, layers)
        failed = [item for item in results if item['status'] == 'failed']
        for item in results:
            LOG.info('%-8s %-36s %-6s %s', item['layer'], item['check_name'], item['status'], item['details'] or '')
        blocking = [item for item in failed if item['severity'] == DQ_FAIL_SEVERITY]
        if blocking:
            raise QualityError('; '.join((f"{item['check_name']}: {item['details']}" for item in blocking)))
    except Exception as error:
        repository.log_finish(get_connection, log_id, 'failed', 0, f'{error}\n{traceback.format_exc()}'[:2000], rows_rejected=None)
        raise
    repository.log_finish(get_connection, log_id, 'success', len(results), None, rows_rejected=len(failed))
    return {'checks': len(results), 'warnings': len(failed)}
