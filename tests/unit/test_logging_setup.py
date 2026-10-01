"""User report: a 500's server-side traceback (the diagnosticId printed
in the browser) was only ever visible live in the terminal window running
run.bat - no persistent record once it scrolled past or the window
closed. configure_logging() makes the app's own logger also write to a
rotating file under the data directory.
"""
from __future__ import annotations

import importlib
import logging


def _reload_logging_setup():
    """Fresh import so each test gets its own module-level `_configured`
    flag and the real db.paths module (re-imported to pick up whatever
    PDF_INTELLIGENCE_DATA_DIR monkeypatch is active for this test)."""
    import pdf_document_intelligence.db.paths as paths_module
    import pdf_document_intelligence.logging_setup as logging_setup_module

    importlib.reload(paths_module)
    importlib.reload(logging_setup_module)
    return logging_setup_module, paths_module


def test_configure_logging_writes_to_a_file(tmp_path, monkeypatch):
    monkeypatch.setenv("PDF_INTELLIGENCE_DATA_DIR", str(tmp_path))
    logging_setup_module, paths_module = _reload_logging_setup()

    logger = logging.getLogger("pdf_document_intelligence")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    logging_setup_module.configure_logging()
    try:
        logger.error("a test error message")
        for handler in logger.handlers:
            handler.flush()

        log_path = paths_module.get_log_path()
        assert log_path.is_file()
        assert "a test error message" in log_path.read_text(encoding="utf-8")
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)


def test_configure_logging_is_idempotent(tmp_path, monkeypatch):
    """Called again (e.g. a module reimport during tests, or a future
    second entry point) must not pile up duplicate handlers - the same
    message would otherwise be written to the log file multiple times."""
    monkeypatch.setenv("PDF_INTELLIGENCE_DATA_DIR", str(tmp_path))
    logging_setup_module, paths_module = _reload_logging_setup()

    logger = logging.getLogger("pdf_document_intelligence")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    logging_setup_module.configure_logging()
    handler_count_after_first_call = len(logger.handlers)
    logging_setup_module.configure_logging()

    try:
        assert len(logger.handlers) == handler_count_after_first_call
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
