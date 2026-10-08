import io
import logging

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

import httpx  # noqa: E402
from fastapi import FastAPI  # noqa: E402

from pretty_terminal_logs import setup_logging  # noqa: E402
from pretty_terminal_logs.fastapi import LoggingMiddleware  # noqa: E402


@pytest.fixture
def stream():
    root = logging.getLogger()
    saved, level = list(root.handlers), root.level
    buffer = io.StringIO()
    setup_logging(stream=buffer, color=False)
    yield buffer
    root.handlers[:] = saved
    root.setLevel(level)


def make_app():
    app = FastAPI()
    app.add_middleware(LoggingMiddleware)

    @app.get("/v1/dashboard")
    async def dashboard():
        logging.getLogger("handler").info("inside handler")
        return {"ok": True}

    @app.get("/boom")
    async def boom():
        raise RuntimeError("kaput")

    return app


async def test_request_is_logged_with_request_id(stream):
    transport = httpx.ASGITransport(app=make_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.get("/v1/dashboard", headers={"x-request-id": "abc123"})
    assert response.headers["x-request-id"] == "abc123"
    out = stream.getvalue()
    assert "GET /v1/dashboard" in out
    assert "status=200" in out and "duration=" in out and "req=abc123" in out
    assert "inside handler" in out  # handler logs share the request id
    assert out.count("req=abc123") == 2


async def test_request_id_generated_and_isolated_between_requests(stream):
    transport = httpx.ASGITransport(app=make_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        first = await client.get("/v1/dashboard")
        second = await client.get("/v1/dashboard")
    assert first.headers["x-request-id"] != second.headers["x-request-id"]


async def test_unhandled_exception_is_logged_as_error(stream):
    transport = httpx.ASGITransport(app=make_app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.get("/boom")
    assert response.status_code == 500
    out = stream.getvalue()
    assert "ERROR" in out and "GET /boom" in out and "status=500" in out
