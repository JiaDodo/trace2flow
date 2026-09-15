"""Entrypoint for the source-pinned final Agent/workflow evaluation bundle."""

from .agent_report import freeze_main

if __name__ == "__main__":
    raise SystemExit(freeze_main())
