"""Перенос одного источника из stg в ods с записью в журнал (ФТ-4, ФТ-6).

Модуль не импортирует Airflow. Как и loader.py, получает функцию открытия соединения.
"""
import logging
import traceback

from bankflow_lib import repository
from bankflow_lib.config import ODS_MAX_REJECT_SHARE

LOG = logging.getLogger(__name__)


def load_table(get_connection, source, ds, run_id, attempt):
    """Грузит источник в ods за дату ds. Возвращает счётчики.

    Журнал: строка «running» пишется до работы (в отдельном соединении), итог после.
    Каждая попытка Airflow даёт свою строку. Падение базы или слишком много отбраковки
    записывается как failed, и исключение уходит дальше, в Airflow.
    """
    log_id = repository.log_start(get_connection, source, ds, "ods", run_id, attempt)
    try:
        counts = repository.call_ods_function(get_connection, source, ds, ODS_MAX_REJECT_SHARE)
        counts["loaded"] = counts["stg_rows"] - counts["duplicates"] - counts["rejected"]
        LOG.info("%-12s stg %s, дублей %s, отбраковано %s, новых %s, изменено %s",
                 source, counts["stg_rows"], counts["duplicates"], counts["rejected"],
                 counts["inserted"], counts["updated"])
    except Exception as error:
        # данные откатились вместе с транзакцией функции; в журнале остаётся причина
        repository.log_finish(get_connection, log_id, "failed", 0, f"{error}\n{traceback.format_exc()}"[:2000])
        raise
    repository.log_finish(get_connection, log_id, "success", counts["loaded"], None,
                          rows_rejected=counts["rejected"])
    return counts
