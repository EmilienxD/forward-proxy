"""Flask app and logging for the forward proxy."""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime

import requests
from flask import Flask, Response, request

logger = logging.getLogger("proxy_debugger")

# Hop-by-hop headers that must NOT be forwarded
HOP_BY_HOP = frozenset([
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
    "host",  # We set our own Host via requests
])

_request_counter = 0

# Set by configure_logging
CYAN = GREEN = YELLOW = RED = BOLD = RESET = ""


def configure_logging(log_path: str, *, no_color: bool) -> None:
    """Attach file + console handlers and set ANSI color globals for console output."""
    global CYAN, GREEN, YELLOW, RED, BOLD, RESET

    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter("%(message)s")

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    use_color = not no_color
    CYAN = "\033[96m" if use_color else ""
    GREEN = "\033[92m" if use_color else ""
    YELLOW = "\033[93m" if use_color else ""
    RED = "\033[91m" if use_color else ""
    BOLD = "\033[1m" if use_color else ""
    RESET = "\033[0m" if use_color else ""


def _separator(char: str = "─", width: int = 72) -> str:
    return char * width


def _pretty_json(text: str) -> str:
    try:
        return json.dumps(json.loads(text), indent=2, ensure_ascii=False)
    except (ValueError, TypeError):
        return text


def _truncate(text: str, max_chars: int = 10000000) -> str:
    if len(text) > max_chars:
        return text[:max_chars] + f"\n… (truncated, {len(text)} total chars)"
    return text


def log_request(req_id: str, method: str, path: str, params, headers, body: bytes) -> None:
    lines = [
        _separator("═"),
        f"{BOLD}{CYAN}▶  REQUEST  [{req_id}]{RESET}",
        f"  Time    : {datetime.utcnow().isoformat()}Z",
        f"  Method  : {BOLD}{method}{RESET}",
        f"  Path    : {path}",
        f"  Params  : {dict(params) if params else '—'}",
        f"  Headers :",
    ]
    for k, v in headers.items():
        lines.append(f"    {k}: {v}")

    if body:
        decoded = body.decode("utf-8", errors="replace")
        lines += [
            "  Body    :",
            _truncate(_pretty_json(decoded)),
        ]
    else:
        lines.append("  Body    : (empty)")

    logger.info("\n".join(lines))


def log_response(req_id: str, status: int, headers, body: bytes, elapsed_ms: float) -> None:
    color = GREEN if status < 400 else (YELLOW if status < 500 else RED)
    lines = [
        _separator(),
        f"{BOLD}{color}◀  RESPONSE [{req_id}]  {status}{RESET}",
        f"  Elapsed : {elapsed_ms:.1f} ms",
        f"  Headers :",
    ]
    for k, v in headers.items():
        lines.append(f"    {k}: {v}")

    if body:
        decoded = body.decode("utf-8", errors="replace")
        lines += [
            "  Body    :",
            _truncate(_pretty_json(decoded)),
        ]
    else:
        lines.append("  Body    : (empty)")

    lines.append(_separator("═"))
    logger.info("\n".join(lines))


def _next_id() -> str:
    global _request_counter
    _request_counter += 1
    return f"{_request_counter:05d}"


def create_app(target_base: str) -> Flask:
    """Build a Flask app that forwards all routes to ``target_base``."""
    base = target_base.rstrip("/")
    app = Flask(__name__)

    @app.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    @app.route("/<path:path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    def proxy(path: str):
        req_id = _next_id()

        upstream_url = f"{base}/{path}" if path else base
        if request.query_string:
            upstream_url += "?" + request.query_string.decode("utf-8")

        fwd_headers = {
            k: v for k, v in request.headers.items()
            if k.lower() not in HOP_BY_HOP
        }

        body = request.get_data()

        log_request(req_id, request.method, upstream_url, request.args, fwd_headers, body)

        t0 = time.perf_counter()
        try:
            upstream_resp = requests.request(
                method=request.method,
                url=upstream_url,
                headers=fwd_headers,
                data=body,
                allow_redirects=False,
                stream=True,
                timeout=60,
            )
        except requests.exceptions.RequestException as exc:
            error_msg = str(exc)
            logger.error(
                f"\n{_separator()}\n"
                f"{RED}{BOLD}✗  ERROR   [{req_id}]{RESET}\n"
                f"  {error_msg}\n"
                f"{_separator('═')}"
            )
            return Response(
                json.dumps({"proxy_error": error_msg}),
                status=502,
                content_type="application/json",
            )

        elapsed_ms = (time.perf_counter() - t0) * 1000
        resp_body = upstream_resp.content

        resp_headers = {
            k: v for k, v in upstream_resp.headers.items()
            if k.lower() not in HOP_BY_HOP
        }

        log_response(req_id, upstream_resp.status_code, resp_headers, resp_body, elapsed_ms)

        return Response(
            resp_body,
            status=upstream_resp.status_code,
            headers=resp_headers,
        )

    return app
