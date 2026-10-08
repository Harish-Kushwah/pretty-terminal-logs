"""Throughput benchmark: python benchmarks/bench.py [N ...]   (default: 10000 100000)

Measures each stage on a realistic mix of formats (app format, generic text, JSON, raw).
"""

import io
import logging
import sys
import time

from pretty_terminal_logs.colors import get_theme
from pretty_terminal_logs.config import Config
from pretty_terminal_logs.formatter import EntryFormatter, PrettyFormatter
from pretty_terminal_logs.parser import StreamParser
from pretty_terminal_logs.renderer import Renderer

TRACE = "d8be77d2-2375-4b71-a818-b676cd5e80da"
USER = "22e2604a-b1e1-40c5-83b8-27312f6bcb71"
TEMPLATES = [
    f"[INFO] [t={TRACE} u={USER} mod=dashboard_report api= req=] Repo - Fetching row {{i}}",
    f"[WARNING] [t={TRACE} u={USER} mod=utils api= req=] Ctl: slow. old_id={TRACE}, timeout=3s",
    "2026-10-07 15:44:12 INFO dashboard_report Fetching data {i}",
    '{{"timestamp": "2026-10-07T15:44:12", "level": "INFO", "message": "m {i}", "trace_id": "a"}}',
    "WARNING:root:Disk usage at 91% {i}",
    "something unparseable {i}",
]


def timed(label: str, count: int, func) -> None:
    start = time.perf_counter()
    func()
    elapsed = time.perf_counter() - start
    print(f"  {label:<28} {elapsed:7.3f}s  {count / elapsed:>12,.0f} lines/s")


def bench(count: int) -> None:
    print(f"{count:,} lines")
    lines = [TEMPLATES[i % len(TEMPLATES)].format(i=i) for i in range(count)]
    config = Config()
    theme = get_theme(config.theme)

    def parse_only() -> None:
        parser = StreamParser()
        for line in lines:
            parser.parse(line)

    parser = StreamParser()
    entries = [parser.parse(line) for line in lines]
    layout = EntryFormatter(config, theme)

    def full(color: bool) -> None:
        renderer = Renderer(theme, color)
        parser = StreamParser()
        for line in lines:
            renderer.render(layout.format(parser.parse(line)))

    def stdlib() -> None:
        formatter = PrettyFormatter(color=False)
        record = logging.getLogger("bench").makeRecord(
            "bench",
            logging.INFO,
            "f.py",
            1,
            "Fetching dashboard report",
            (),
            None,
            extra={"trace_id": TRACE, "duration": "12ms"},
        )
        for _ in range(count):
            formatter.format(record)

    timed("parse", count, parse_only)
    timed("format (pre-parsed)", count, lambda: [layout.format(e) for e in entries])
    timed("parse+format+render, plain", count, lambda: full(False))
    timed("parse+format+render, color", count, lambda: full(True))
    timed("logging.Formatter.format()", count, stdlib)
    sink = io.StringIO()
    renderer = Renderer(theme, False)
    for e in entries:
        sink.write(renderer.render(layout.format(e)) + "\n")
    print(f"  (output size: {sink.tell() / 1e6:.1f} MB)")


if __name__ == "__main__":
    for n in [int(a) for a in sys.argv[1:]] or [10_000, 100_000]:
        bench(n)
