"""ServiceNow MCP server: JSON-RPC over HTTP, the shape SynergyAI's MCP client uses.

POST /mcp (also / , /jobs, /jobs/mcp): the job tools. POST /deploy (also /deploy/mcp): install_app.
Settings come from the environment (run.sh loads .env); SN_INSTANCE=mock is a built-in fake instance.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

import guard
from config import Config
from deploy import DeployToolset, run_command
from errors import ConnectorError
from fixture_backend import FixtureBackend
from jobs import JobsToolset
from live_backend import LiveBackend, TokenProvider, http_transport
from rpc import CallLog, Server, error_response

APP_DIR = Path(__file__).resolve().parent
JOBS_PATHS = ("/", "/mcp", "/jobs", "/jobs/mcp")
DEPLOY_PATHS = ("/deploy", "/deploy/mcp")


def mock_state_path(app_dir: Path) -> Path:
    return Path(app_dir) / "var" / "mock-state.json"


def build_server(config: Config, toolset: str, app_dir: Path, authorization: str | None = None,
                 transport=None, runner=None) -> Server:
    """The Server for one request: the job tools or the deploy tool."""
    app_dir = Path(app_dir)
    if toolset == "deploy":
        # No call log: deploy arguments are whole project files and arrive before the token check.
        return Server(DeployToolset(config, runner or run_command, app_dir / "var" / "deploy", authorization))
    if config.is_mock:
        # The mock remembers claims, notes and completions (var/mock-state.json); reset_mock.py forgets them.
        return Server(JobsToolset(config, FixtureBackend.with_state(app_dir / "fixtures" / "mock.json",
                                                                    mock_state_path(app_dir))),
                      CallLog(app_dir / "log" / "calls.jsonl"))
    transport = transport or http_transport(config.timeout)
    tokens = TokenProvider(config, transport, app_dir / "var" / "cache")
    return Server(JobsToolset(config, LiveBackend(config, tokens, transport)))


def create_app(env: dict | None = None, app_dir: Path = APP_DIR, transport=None, runner=None) -> FastAPI:
    app = FastAPI(title="ServiceNow MCP")
    # A bad setting does not stop the server: every request answers with it, so the app's MCP test shows the reason.
    try:
        config, config_error = Config.from_env(env), None
    except ConnectorError as e:
        config, config_error = None, e

    async def handle(request: Request, toolset: str):
        refused = guard.check(request.method, request.headers.get("origin"), request.headers.get("content-type"))
        if refused is not None:
            return JSONResponse(error_response(None, -32600, refused[1]), status_code=refused[0])
        try:
            rpc = json.loads(await request.body())
        except ValueError:
            return JSONResponse(error_response(None, -32700, "Parse error"))
        if not isinstance(rpc, dict):
            return JSONResponse(error_response(None, -32600, "Invalid Request"))
        if config_error is not None:
            return JSONResponse(error_response(rpc.get("id"), -32000, f"{config_error.code}: {config_error}"))
        try:
            server = build_server(config, toolset, app_dir, request.headers.get("authorization"), transport, runner)
        except ConnectorError as e:
            return JSONResponse(error_response(rpc.get("id"), -32000, f"{e.code}: {e}"))
        # Tools block (wait_for_jobs up to 140 s, deploy for minutes): a worker thread, not the event loop.
        response = await run_in_threadpool(server.handle, rpc)
        if response is None:
            return Response(status_code=202)
        return JSONResponse(response)

    def endpoint(toolset: str):
        async def route(request: Request):
            return await handle(request, toolset)
        return route

    methods = ["GET", "POST", "PUT", "PATCH", "DELETE"]   # anything but POST gets the guard's 405
    for path in JOBS_PATHS:
        app.add_api_route(path, endpoint("jobs"), methods=methods)
    for path in DEPLOY_PATHS:
        app.add_api_route(path, endpoint("deploy"), methods=methods)
    return app


def main() -> None:  # pragma: no cover
    import uvicorn
    ours = logging.getLogger("servicenow_mcp")
    ours.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
    ours.addHandler(handler)
    host = os.environ.get("SN_HOST") or "127.0.0.1"
    port = int(os.environ.get("SN_PORT") or "8772")
    uvicorn.run(create_app(), host=host, port=port, timeout_keep_alive=5)


if __name__ == "__main__":  # pragma: no cover
    main()
