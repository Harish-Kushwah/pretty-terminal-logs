import asyncio
import logging
import threading

from pretty_terminal_logs import clear_context, get_context_logger, log_context, set_context
from pretty_terminal_logs.context import get_context
from pretty_terminal_logs.formatter import PrettyFormatter, record_to_entry


def emit(logger, msg="m"):
    """Format a record the way a handler would, from the calling context."""
    captured = []

    class Capture(logging.Handler):
        def emit(self, record):
            captured.append(PrettyFormatter().format(record))

    handler = Capture()
    logger.addHandler(handler)
    try:
        logger.warning(msg)
    finally:
        logger.removeHandler(handler)
    return captured[0]


def make_logger(name):
    logger = logging.getLogger(name)
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    return logger


def test_set_and_clear_context():
    clear_context()
    set_context(trace_id="abc", user_id="123", request_id="xyz")
    out = emit(make_logger("ctx.sync"))
    assert "trace=abc │ user=123 │ req=xyz" in out
    clear_context()
    assert dict(get_context()) == {}
    assert "trace=" not in emit(make_logger("ctx.sync"))


def test_set_context_merges():
    clear_context()
    set_context(trace_id="a")
    set_context(user_id="b")
    assert dict(get_context()) == {"trace_id": "a", "user_id": "b"}
    clear_context()


def test_nested_log_context_and_cleanup():
    clear_context()
    with log_context(trace_id="outer", user_id="u"):
        with log_context(trace_id="inner"):
            assert get_context()["trace_id"] == "inner"
            assert get_context()["user_id"] == "u"
        assert get_context()["trace_id"] == "outer"
    assert dict(get_context()) == {}


def test_log_context_restored_after_exception():
    clear_context()
    try:
        with log_context(trace_id="x"):
            raise RuntimeError
    except RuntimeError:
        pass
    assert dict(get_context()) == {}


async def test_async_tasks_do_not_leak_context():
    clear_context()
    logger = make_logger("ctx.async")
    results = {}

    async def task(name):
        with log_context(trace_id=name):
            await asyncio.sleep(0.01)  # let the other task run in between
            results[name] = emit(logger, f"Task {name}")

    await asyncio.gather(task("A"), task("B"))
    assert "trace=A" in results["A"] and "trace=B" not in results["A"]
    assert "trace=B" in results["B"] and "trace=A" not in results["B"]
    assert dict(get_context()) == {}


async def test_set_context_inside_task_does_not_leak_to_parent():
    clear_context()

    async def child():
        set_context(trace_id="child")

    await asyncio.create_task(child())
    assert dict(get_context()) == {}


def test_threads_have_isolated_context():
    clear_context()
    seen = {}

    def worker(name):
        set_context(trace_id=name)
        seen[name] = get_context()["trace_id"]

    threads = [threading.Thread(target=worker, args=(n,)) for n in ("t1", "t2", "t3")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert seen == {"t1": "t1", "t2": "t2", "t3": "t3"}
    assert dict(get_context()) == {}


def test_context_logger_attaches_context_and_is_optional():
    logger = get_context_logger(
        "ctx.bound", trace_id="abc", user_id="123", module="dashboard_report"
    )
    inner = make_logger("ctx.bound")
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    inner.addHandler(Capture())
    logger.info("Fetching dashboard report", extra={"duration": "5ms"})
    entry = record_to_entry(records[0])
    assert (entry.trace_id, entry.user_id, entry.module) == ("abc", "123", "dashboard_report")
    assert entry.extra == {"duration": "5ms"}
    assert entry.message == "Fetching dashboard report"

    inner.info("plain logging still works")
    assert record_to_entry(records[1]).trace_id is None


def test_context_logger_bind_and_precedence():
    clear_context()
    base = get_context_logger("ctx.bind", trace_id="a")
    child = base.bind(user_id="u")
    assert child.extra == {"trace_id": "a", "user_id": "u"}
    assert base.extra == {"trace_id": "a"}

    inner = make_logger("ctx.bind")
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    inner.addHandler(Capture())
    with log_context(trace_id="from-var", request_id="r"):
        child.info("x")
        entry = record_to_entry(records[0])  # contextvars are read at format time
    assert entry.trace_id == "a"  # bound context beats contextvars
    assert entry.request_id == "r"
