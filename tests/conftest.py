"""Test-session-wide isolation: point PDF_INTELLIGENCE_DATA_DIR at a
throwaway temp directory *before* any test module imports
pdf_document_intelligence.api.app (which opens the SQLite connection as a
module-level side effect) - this must run at collection time, not inside a
fixture, or the real default user data dir would get touched first.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="pdi_test_data_"))
os.environ["PDF_INTELLIGENCE_DATA_DIR"] = str(_TEST_DATA_DIR)
