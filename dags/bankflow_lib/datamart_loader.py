import logging
import traceback

from bankflow_lib import repository

LOG = logging.getLogger(__name__)


def load_table(get_connection, source, ds, run_id, attempt):
    log_id = repository.log_start(get_connection, f"dm_{source}", ds, "datamart", run_id, attempt)
    try:
        counts = repository.call_datamart_function(get_connection, source, ds)
        LOG.info("%-10s строк в факте %s, строк в витрине %s", source, counts["src_rows"], counts["inserted"])
    except Exception as error:
        repository.log_finish(get_connection, log_id, "failed", 0, f"{error}\n{traceback.format_exc()}"[:2000])
        raise
    repository.log_finish(get_connection, log_id, "success", counts["inserted"], None)
    return counts
