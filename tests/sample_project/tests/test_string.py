import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from myapp.string_utils import upper, lower

def test_upper():
    assert upper("hello") == "HELLO"

def test_lower():
    assert lower("HELLO") == "hello"

import pytest

def test_will_fail():
    """This test intentionally fails to verify failure tracking."""
    assert upper("hello") == "hello"

@pytest.mark.skip(reason="testing skip tracking")
def test_skipped():
    pass
