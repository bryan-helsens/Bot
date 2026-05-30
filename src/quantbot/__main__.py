"""Enable ``python -m quantbot`` to invoke the CLI."""

from __future__ import annotations

from quantbot.cli import app

if __name__ == "__main__":
    app()
