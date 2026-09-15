"""CLI entrypoint for declaration-gated compilation of reviewed Agent runs."""

from .agent_review import build_main

if __name__ == "__main__":
    raise SystemExit(build_main())
