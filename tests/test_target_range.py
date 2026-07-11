import sys
from pathlib import Path

import pytest

# Add parent directory to path so imports work
sys.path.insert(0, str(Path(__file__).parent.parent))

from eljam3ia_odds_scanner import parse_target


def test_range_string():
    assert parse_target("1.3..1.45") == (1.3, 1.45)


def test_single_value_string():
    assert parse_target("1.4") == (1.4, 1.4)


def test_single_float():
    assert parse_target(1.4) == (1.4, 1.4)


def test_reversed_range_is_sorted():
    assert parse_target("1.45..1.3") == (1.3, 1.45)


def test_bad_input_raises():
    with pytest.raises(ValueError):
        parse_target("abc")
