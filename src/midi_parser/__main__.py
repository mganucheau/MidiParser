"""Entry point: launch the MIDI Organizer GUI."""

from __future__ import annotations

import faulthandler
import logging
import sys
import threading
from pathlib import Path


def _log_dir() -> Path:
    return Path.home() / ".midi_parser"


def _setup_crash_logging() -> Path:
    log_dir = _log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "app.log"
    fault_path = log_dir / "fault.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
        force=True,
    )

    try:
        fault_file = fault_path.open("a", encoding="utf-8")
        faulthandler.enable(file=fault_file, all_threads=True)
    except OSError:
        faulthandler.enable(all_threads=True)

    def _excepthook(exc_type, exc, tb) -> None:
        logging.error("Uncaught exception", exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)

    def _thread_excepthook(args: threading.ExceptHookArgs) -> None:
        logging.error(
            "Uncaught thread exception in %s",
            args.thread.name if args.thread else "?",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook
    logging.info("MIDI Organizer starting")
    return log_path


def main() -> None:
    _setup_crash_logging()
    try:
        from midi_parser.app import run_app

        run_app()
    except Exception:
        logging.exception("Fatal error launching app")
        raise


if __name__ == "__main__":
    main()
