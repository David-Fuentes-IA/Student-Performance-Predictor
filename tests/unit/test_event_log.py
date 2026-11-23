"""Unit: the error log ("bitacora de errores") without a database: what is captured, how it is classified, the
memory store's filters, and that a failing store never breaks the application."""
import logging
import unittest
from datetime import datetime, timedelta

from core import event_log
from core.event_log import EventLog, InMemoryEventLogStore, classify


def event(message="x", level="WARNING", minutes_ago=0, **extra):
    return {"created_at": datetime(2026, 11, 22, 12, 0) - timedelta(minutes=minutes_ago), "level": level,
            "kind": classify(message), "source": "test", "message": message, **extra}


class ClassifyTests(unittest.TestCase):
    def test_each_kind_of_failure_gets_its_category(self):
        cases = {
            "ADMIN AUTH FAILED | DELETE /admin/api/groups/x from 1.2.3.4 (wrong password)": "seguridad",
            "REQUEST REJECTED | 400 POST /admin/api/groups | Se esperaba un JSON valido.": "solicitud rechazada",
            "get_group_dashboard_data raised GroupNotFoundError: group 'X' not found": "no encontrado",
            "Data access failed: MongoDB connection failed": "base de datos",
            "Record S1 skipped: invalid grade": "datos invalidos",
            "Unexpected error: boom": "error inesperado",
            "something else": "otro",
        }
        for message, kind in cases.items():
            with self.subTest(message=message):
                self.assertEqual(classify(message), kind)


class MemoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = InMemoryEventLogStore()
        self.store.add_many([event("REQUEST REJECTED | 404 GET /a", minutes_ago=30, path="/a", ref="AAA11111"),
                             event("Unexpected error: boom", level="ERROR", minutes_ago=20),
                             event("ADMIN AUTH FAILED | GET /admin/api/stats", minutes_ago=10)])

    def test_newest_first_with_total_and_paging(self):
        total, items = self.store.query(limit=2, skip=0)
        self.assertEqual(total, 3)
        self.assertEqual([i["kind"] for i in items], ["seguridad", "error inesperado"])
        self.assertEqual(len(self.store.query(limit=2, skip=2)[1]), 1)

    def test_filters_by_level_kind_text_and_dates(self):
        self.assertEqual(self.store.query(level="ERROR", limit=10)[0], 1)
        self.assertEqual(self.store.query(kind="seguridad", limit=10)[0], 1)
        self.assertEqual(self.store.query(text="aaa11111", limit=10)[0], 1)     # reference code, case-insensitive
        since = datetime(2026, 11, 22, 11, 45)
        self.assertEqual(self.store.query(since=since, limit=10)[0], 1)

    def test_counts_by_level_and_kind(self):
        counts = self.store.counts()
        self.assertEqual(counts["total"], 3)
        self.assertEqual(counts["by_level"], {"WARNING": 2, "ERROR": 1, "CRITICAL": 0})

    def test_memory_is_bounded(self):
        small = InMemoryEventLogStore(limit=5)
        small.add_many([event(str(i)) for i in range(20)])
        self.assertEqual(small.query(limit=50)[0], 5)


class FailingStore:
    persistent = True

    def __init__(self):
        self.fail = True
        self.saved = []

    def add_many(self, events):
        if self.fail:
            raise ConnectionError("database down")
        self.saved.extend(events)


class HandlerTests(unittest.TestCase):
    def setUp(self):
        self.log = EventLog()
        self.log.store = InMemoryEventLogStore()
        self.logger = logging.getLogger("student_predictor.tests.event_log")
        self.logger.addHandler(self.log.handler)
        self.addCleanup(self.logger.removeHandler, self.log.handler)

    def test_warnings_and_errors_are_kept_info_and_risk_alerts_are_not(self):
        self.logger.info("routine")
        self.logger.warning("RISK ALERT | student S1 is high risk")    # the system working, not a failure
        self.logger.warning("Record S2 skipped: invalid grade")
        try:
            raise ValueError("bad")
        except ValueError:
            self.logger.error("Unexpected error: bad", exc_info=True)
        self.log.flush()
        total, items = self.log.store.query(limit=10)
        self.assertEqual(total, 2)
        error = next(i for i in items if i["level"] == "ERROR")
        self.assertEqual(error["exception"], "ValueError")
        self.assertIn("Traceback", error["traceback"])

    def test_events_survive_a_store_outage_and_are_written_when_it_returns(self):
        store = FailingStore()
        self.log.store = store
        self.logger.warning("Data access failed: database down")
        self.assertEqual(self.log.flush(), 0)
        self.assertEqual(self.log.pending(), 1)
        store.fail = False
        self.assertEqual(self.log.flush(), 1)
        self.assertEqual(store.saved[0]["kind"], "base de datos")

    def test_long_messages_are_cut(self):
        self.logger.warning("x" * 10_000)
        self.log.flush()
        self.assertLess(len(self.log.store.query(limit=1)[1][0]["message"]), 2100)


class LogInjectionTests(unittest.TestCase):
    def test_a_line_break_in_user_input_cannot_forge_a_log_line(self):
        from core.logger import _OneLineFormatter

        formatter = _OneLineFormatter("%(levelname)s | %(message)s")
        record = logging.LogRecord("x", logging.WARNING, "", 0,
                                   "REQUEST REJECTED | 404 GET /api/groups/x\r\nERROR | ADMIN AUTH OK", None, None)
        text = formatter.format(record)
        self.assertNotIn("\n", text)
        self.assertIn("\\r\\nERROR", text)


class InstallTests(unittest.TestCase):
    def test_install_attaches_the_handler_once(self):
        event_log.install(InMemoryEventLogStore())
        event_log.install(InMemoryEventLogStore())
        root = logging.getLogger("student_predictor")
        self.assertEqual(sum(1 for h in root.handlers if isinstance(h, event_log.EventLogHandler)), 1)


if __name__ == "__main__":
    unittest.main()
