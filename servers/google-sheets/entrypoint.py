import builtins
import os
import sys


_orig_print = builtins.print


def _safe_print(*args, **kwargs):
    # In stdio transport, stdout is reserved for the MCP JSON-RPC protocol.
    # Any incidental prints must go to stderr.
    if "file" not in kwargs:
        kwargs["file"] = sys.stderr
    return _orig_print(*args, **kwargs)


builtins.print = _safe_print


def main() -> None:
    # Prefer unbuffered stderr logs (stdout is protocol)
    os.environ.setdefault("PYTHONUNBUFFERED", "1")

    # Defer import until after print monkeypatch
    from mcp_google_sheets import server

    server.main()


if __name__ == "__main__":
    main()
