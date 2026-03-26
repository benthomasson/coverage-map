import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from myapp.math_utils import add, subtract, multiply

def test_add():
    assert add(1, 2) == 3

def test_subtract():
    assert subtract(5, 3) == 2

def test_multiply():
    assert multiply(2, 3) == 6

def test_add_negative():
    assert add(-1, -2) == -3

class TestMathClass:
    def test_add_zero(self):
        assert add(0, 0) == 0

    def test_subtract_same(self):
        assert subtract(5, 5) == 0
