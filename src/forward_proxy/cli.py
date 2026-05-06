"""CLI entry point for the forward proxy."""

from __future__ import annotations

import argparse

import forward_proxy.proxy as proxy


def main() -> None:
    parser = argparse.ArgumentParser(description="HTTP proxy debugger")
    parser.add_argument(
        "--target",
        required=True,
        help="Base URL of the upstream service (e.g. https://api.example.com)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="Local port to listen on (default: 5000)",
    )
    parser.add_argument(
        "--log",
        default="proxy_debug.log",
        help="Path to the log file (default: proxy_debug.log)",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored console output",
    )
    args = parser.parse_args()

    proxy.configure_logging(args.log, no_color=args.no_color)
    target_base = args.target.rstrip("/")

    startup_msg = (
        f"\n{proxy._separator('═')}\n"
        f"{proxy.BOLD}🔍  Proxy Debugger started{proxy.RESET}\n"
        f"  Listening on : http://localhost:{args.port}\n"
        f"  Forwarding to: {target_base}\n"
        f"  Log file     : {args.log}\n"
        f"{proxy._separator('═')}\n"
    )
    proxy.logger.info(startup_msg)

    app = proxy.create_app(args.target)
    app.run(host="0.0.0.0", port=args.port, debug=False)
