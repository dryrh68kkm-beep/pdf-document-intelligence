import os

import pytest


@pytest.fixture(autouse=True)
def _restore_environ():
    """store_suite.app sets PDI_* defaults at import (as it must in production);
    keep them from leaking into the PDF app's own tests."""
    before = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(before)
