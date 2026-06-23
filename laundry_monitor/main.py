from __future__ import annotations

import logging

from .config import load_settings
from .monitor import run_monitor


def main() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    run_monitor(settings)


if __name__ == "__main__":
    main()
