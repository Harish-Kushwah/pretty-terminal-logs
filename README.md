# Pretty Terminal Logs

Make application logs readable.

Turn this:

```text
[INFO] [t=d8be77d2-2375-4b71-a818-b676cd5e80da u=22e2604a-b1e1-40c5-83b8-27312f6bcb71 mod=dashboard_report api= req=] DashboardReportRepository - Fetching from v_material_with_chemical_and_msds_compliance
[WARNING] [t=d8be77d2-2375-4b71-a818-b676cd5e80da u=22e2604a-b1e1-40c5-83b8-27312f6bcb71 mod=utils api= req=] AsyncTaskVisibilityController: extended visibility. old_id=7fe05753-441e-4176-94c5-4c216a38d2a4, new_id=7fe05753-441e-4176-94c5-4c216a38d2a4, timeout=361.2s
```

into this (colored in a terminal):

```text
--:--:-- │ INFO     │ dashboard_report
          └─ DashboardReportRepository
             Fetching from v_material_with_chemical_and_msds_compliance
             trace=d8be77d2...80da │ user=22e2604a...cb71
--:--:-- │ WARNING  │ utils
          └─ AsyncTaskVisibilityController
             extended visibility
             trace=d8be77d2...80da │ user=22e2604a...cb71
             old_id=7fe05753...d2a4
             new_id=7fe05753...d2a4
             timeout=361.2s
```

Works with Python `logging` and with existing log files, with no changes to your application's logging calls.
(`--:--:--` appears because those two lines carry no timestamp; lines that do are shown as `15:44:12`.)

## Contents

[Installation](#installation) · [Basic usage](#basic-usage) · [CLI](#cli-usage) ·
[Python logging](#python-logging-integration) · [Context](#context-logging) ·
[Configuration](#configuration) · [Themes](#themes) · [JSON logs](#json-logs) ·
[FastAPI](#fastapi-integration) · [Environment variables](#environment-variables) ·
[Development](#development-setup) · [Architecture](#architecture) ·
[Known limitations](#known-limitations) · [Contributing](#contributing) · [License](#license)

## Installation

```bash
pip install pretty-terminal-logs
# optional FastAPI example dependencies
pip install "pretty-terminal-logs[fastapi]"
```

Requires Python 3.10+. Runtime dependencies: `rich` and `pyyaml` (PyYAML is needed for the YAML config file).

## Basic usage

Python, in your application:

```python
import logging
from pretty_terminal_logs import setup_logging

setup_logging()

logger = logging.getLogger(__name__)
logger.info("Application started")
logger.warning("Something looks suspicious")
logger.error("Something failed")
```

Or, without touching the application at all:

```bash
python app.py 2>&1 | pretty-log
```

## CLI usage

```bash
python app.py 2>&1 | pretty-log      # pipe a running program
cat application.log | pretty-log     # pipe a file
pretty-log application.log           # or pass files directly
pretty-log --follow application.log # like tail -f
```

| Option | Effect |
| --- | --- |
| `--color` / `--no-color` | Force colors on/off (overrides auto-detection) |
| `--config FILE` | Load a YAML config file |
| `--theme NAME` | `default`, `minimal` or `high-contrast` |
| `--level LEVEL` | Hide entries below this level (tracebacks of hidden entries are hidden too) |
| `--compact` | One line per entry |
| `--verbose` | Include the date in timestamps |
| `--no-short-ids` | Show full UUIDs |
| `-f`, `--follow FILE` | Follow a file; handles partial lines, truncation/rotation and Ctrl+C |
| `--save FILE` | Also append the input to `FILE` as plain text (see below) |
| `--version`, `--help` | |

Exit codes: `0` success (also on Ctrl+C or a closed pipe), `1` I/O error (e.g. file not found), `2` invalid configuration/usage.

**Colors** are on only for an interactive terminal. They are off for pipes/redirects, `CI` environments,
`NO_COLOR`, and `TERM=dumb`; `--color` / `--no-color` always win. With colors off the output is plain text.

**Saving a shareable log file.** `--save FILE` keeps the pretty output on screen and also appends a plain copy of the
input to `FILE` (parent folders are created, the absolute path is printed to stderr). The copy has no colors, keeps full
UUIDs, and is not affected by `--level`/themes, so it is the version to hand to a person, a ticket, or an AI assistant.
The file is flushed line by line, so it is usable while the process is still running. It refuses to write to a file it is
also reading.

```bash
python app.py 2>&1 | pretty-log --save logs/session.log
pretty-log --follow app.log --save D:/tmp/slice.log
```

**Unparseable lines are never dropped.** They are shown as `RAW`. Indented lines and tracebacks that follow a
record are shown indented beneath it:

```text
--:--:-- │ ERROR    │ database
          └─ DatabaseRepository
             Failed to execute query. error=timeout
             trace=d8be77d2...80da │ user=22e2604a...cb71
             Traceback (most recent call last):
               File "repository.py", line 142, in run
                 result = connection.execute(query)
             TimeoutError: connection timed out
```

Supported input formats (auto-detected per line):

* the app format `[LEVEL] [t=.. u=.. mod=.. api=.. req=..] Logger - message` (also `Logger: message`)
* `2026-10-07 15:44:12 INFO dashboard_report Fetching data` and `2026-10-07 15:44:12 [INFO] Fetching data`
* standard Python logging: `WARNING:root:message` and `<asctime> - <name> - <LEVEL> - <message>`
* JSON, one object per line (see [JSON logs](#json-logs))

Trailing `key=value` pairs at the end of a text message (`... timeout=361.2s`) are moved to separate metadata
lines. Values cannot contain spaces. Empty fields such as `api=` and `req=` are hidden.

## Python logging integration

`setup_logging()` installs one handler on the root logger. Nothing else changes: `logging.getLogger(__name__)`,
`logger.info(...)`, `extra={...}` and `logger.exception(...)` keep working.

```python
setup_logging(
    level="INFO",  # or logging.DEBUG; default INFO
    color=None,  # None/"auto" = detect, True = force on, False = off
    show_timestamp=True,
    show_module=True,
    show_context=True,
    shorten_ids=True,
)
```

Extra keyword arguments: `show_logger`, `theme`, `compact`, `stream` (default `sys.stderr`), `config_file`, and
`force=True` (also remove other root handlers, like `logging.basicConfig(force=True)`). Calling it twice replaces
the previous pretty handler rather than duplicating it. It returns the handler.

`extra={...}` values and context fields appear as metadata. `logger.exception(...)` appends the full traceback,
dimmed, with the final exception line highlighted.

Terminals that cannot encode `│ └─` (for example a redirected Windows stream using cp1252) automatically get an
ASCII layout (`|`, `` `- ``).

## Context logging

Everything here is optional.

```python
from pretty_terminal_logs import set_context, clear_context, log_context, get_context_logger

set_context(trace_id="abc", user_id="123", request_id="xyz")
logger.info("Fetching dashboard")  # ... trace=abc │ user=123 │ req=xyz
clear_context()

with log_context(trace_id="abc", user_id="123"):  # restored on exit, even on errors
    logger.info("Fetching data")

bound = get_context_logger(__name__, trace_id="abc", user_id="123", module="dashboard_report")
bound.info("Fetching dashboard report")  # context attached to every call
```

Recognised fields are `trace_id`, `user_id`, `request_id`, `api` and `module` (the module column); any other key is
shown as extra metadata. Precedence: `extra=` on the call > `get_context_logger` context > `contextvars` context.

The context lives in `contextvars`, so it is isolated per thread and per asyncio task, and tasks do not leak
context into each other (see `tests/test_context.py`). New threads start with an empty context.
Context is read when a record is formatted, so with `QueueHandler`/`QueueListener` (formatting in another
thread) use `get_context_logger` or `extra=` instead of `set_context`.

## Configuration

No configuration is required. Precedence, lowest to highest:
**defaults < config file < environment variables < CLI arguments / `setup_logging()` arguments.**

```yaml
# pretty-log.yaml  (see examples/pretty-log.yaml)
theme: default          # default | minimal | high-contrast
level: INFO             # omit to show everything in the CLI
color: auto             # auto | always | never
display:
  timestamp: true
  module: true
  logger: true
  context: true         # context fields and extra metadata
  shorten_ids: true
context:
  fields: [trace_id, user_id, request_id, api]   # shown on one line, in this order
```

Unknown keys and invalid values are rejected with a clear message (`pretty-log: error: ...`, exit code 2).
`context.fields` may also name extra keys (e.g. `service`) to include them on the context line.

UUID shortening only applies to metadata values that look like UUIDs (`d8be77d2-2375-4b71-a818-b676cd5e80da` ->
`d8be77d2...80da`); message text is never altered.

## Themes

| Theme | Description |
| --- | --- |
| `default` | Multi-line block layout, DEBUG dim, INFO cyan, WARNING yellow, ERROR red, CRITICAL bold white on red |
| `minimal` | One line per entry: `15:44:12 INFO dashboard_report Fetching data` |
| `high-contrast` | Block layout with bold, high-contrast colors and no dim text |

Themes are plain dataclasses of Rich style strings, so adding one is a few lines:

```python
from pretty_terminal_logs.colors import Theme, register_theme

register_theme(Theme(name="mine", info="green", warning="bold yellow", module="blue"))
# then: setup_logging(theme="mine")  /  pretty-log --theme mine
```

## JSON logs

One JSON object per line is rendered with the same renderer. Common field names are recognised
(`timestamp`/`time`/`ts`/`@timestamp`, `level`/`levelname`/`severity`, `message`/`msg`, `logger`/`name`, `module`,
`trace_id`, `user_id`, `request_id`, `api`, `exception`/`traceback`); everything else becomes metadata.

```bash
echo '{"timestamp": "2026-10-07T15:44:12", "level": "INFO", "module": "dashboard_report", "message": "Fetching dashboard", "trace_id": "abc", "user_id": "123"}' | pretty-log --no-color
```

```text
15:44:12 │ INFO     │ dashboard_report
          └─ Fetching dashboard
             trace=abc │ user=123
```

## FastAPI integration

An optional, plain-ASGI middleware (works with FastAPI, Starlette or any ASGI app; FastAPI is not imported by the
library and is not a core dependency). It logs one entry per request and sets `request_id` for everything logged
while handling it. The id comes from the `X-Request-ID` header or is generated, and is returned in the response.

```python
from fastapi import FastAPI
from pretty_terminal_logs import setup_logging
from pretty_terminal_logs.fastapi import LoggingMiddleware

setup_logging()
app = FastAPI()
app.add_middleware(LoggingMiddleware)
```

```text
16:20:01 │ INFO     │ api
          └─ pretty_terminal_logs.access
             GET /v1/dashboard
             req=abc123
             status=200
             duration=3ms
```

The level is INFO for status < 400, WARNING for 4xx, ERROR for 5xx and for unhandled exceptions (logged with the
traceback, then re-raised). See `examples/fastapi_example.py`.

## Environment variables

| Variable | Values |
| --- | --- |
| `PRETTY_LOG_COLOR` | `auto` (default), `always`/`true`, `never`/`false` |
| `PRETTY_LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` (or a number) |
| `PRETTY_LOG_THEME` | `default`, `minimal`, `high-contrast` |
| `PRETTY_LOG_SHORT_IDS` | `true` / `false` |

Also honoured when `color` is `auto`: `NO_COLOR`, `CI`, `TERM=dumb`. Environment variables override the config file
and defaults; CLI arguments override environment variables. Invalid values are reported as errors.

## Development setup

```bash
git clone <repo> && cd pretty-terminal-logs
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Testing

```bash
pytest
ruff check .
mypy src/
python benchmarks/bench.py            # throughput for 10,000 and 100,000 lines
```

Measured on the development machine (Windows 11, Python 3.12; your numbers will differ):

| Stage (100,000 mixed lines) | Time | Throughput |
| --- | --- | --- |
| parse | 0.51 s | ~198k lines/s |
| parse + format + render (plain) | 1.82 s | ~55k lines/s |
| parse + format + render (color) | 2.08 s | ~48k lines/s |
| `logging.Formatter.format()` per record | 1.62 s | ~62k records/s |

## Architecture

```text
 Application (logging)          log files / pipes / stdin
        │                                 │
        ▼                                 ▼
  PrettyFormatter                     pretty-log (cli.py)
  record_to_entry()                   StreamParser / AutoParser
        │                                 │      (parser.py)
        └──────────────┬──────────────────┘
                       ▼
                  LogEntry            (models.py)  normalized, format-independent
                       │
                       ▼
                EntryFormatter        (formatter.py) layout -> role-tagged Spans, no colors, no I/O
                       │
                       ▼
                   Renderer           (renderer.py) Theme (colors.py) -> text or ANSI string
```

| Module | Responsibility |
| --- | --- |
| `models.py` | `LogEntry`, `Span` |
| `parser.py` | `TextLogParser`, `PythonLogParser`, `JsonLogParser`, `AutoParser`, `StreamParser` (independent of the rest) |
| `formatter.py` | `EntryFormatter` (layout), `PrettyFormatter` (`logging.Formatter`), `setup_logging` |
| `renderer.py` | Spans -> string; resolves styles once at construction |
| `colors.py` | `Theme`, theme registry, color auto-detection |
| `config.py` | `Config`, YAML file, environment variables, validation |
| `context.py` | `contextvars` context, `log_context`, `get_context_logger` |
| `cli.py` | `pretty-log`, follow mode |
| `fastapi.py` | Optional ASGI middleware |

Parsing, formatting and rendering are independent stages: the parser produces `LogEntry` objects, the formatter turns
them into role-tagged spans, and the renderer maps roles to styles. Nothing in the core knows about the CLI, so another
front end (for example a future editor extension) can reuse the parser/formatter/renderer directly. The library is a
presentation layer; it does not replace structured logging or change what your application writes to files.

## Known limitations

* Lines without a timestamp (including the app format shown above) display `--:--:--`; the library does not invent a
  time.
* Text-format `key=value` extraction only reads trailing pairs whose values contain no spaces, commas or semicolons.
  Quoted values are not supported.
* Tracebacks are rendered from their text (dimmed, last line highlighted), not with Rich's traceback panel, so no
  information is lost but there is no syntax highlighting.
* Multi-line records are grouped only through the heuristics above (tracebacks and indented lines). Other
  continuation lines appear as separate `RAW` entries.
* Blank input lines are skipped by the CLI.
* Format detection is per line and heuristic: `<ts> LEVEL name message` treats a leading dotted/underscored token as
  the module name.
* Context is read at format time (see the `QueueHandler` note above).
* Nothing is implemented for the "future" items (VS Code extension, remote streaming, Loki/Elasticsearch/OpenTelemetry,
  Docker/Kubernetes, plugins).
* PyYAML is a core dependency in addition to `rich`, because the YAML config file is part of v0.1.

## Contributing

Issues and pull requests are welcome. Please run `pytest`, `ruff check .` and `mypy src/` before submitting, add tests
for behavior changes, and keep the parser, formatter and renderer independent of each other and of the CLI.

## License

MIT, see [LICENSE](LICENSE).
