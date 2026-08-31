"""
Testes unitários simples para a lógica de value betting.
Corre com: pytest tests/
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from value_finder import expected_value, implied_probability, remove_overround


def test_implied_probability():
    assert implied_probability(2.0) == pytest.approx(0.5)
    assert implied_probability(4.0) == pytest.approx(0.25)


def test_implied_probability_invalid_odd():
    with pytest.raises(ValueError):
        implied_probability(0.9)


def test_remove_overround_sums_to_one():
    odds = [1.90, 2.10, 4.00]
    probs = remove_overround(odds)
    assert sum(probs) == pytest.approx(1.0, abs=1e-9)


def test_expected_value_positive():
    # prob_modelo=0.55, odd=2.10 -> EV = 0.55*2.10 - 1 = 0.155 (15.5%)
    ev = expected_value(0.55, 2.10)
    assert ev == pytest.approx(0.155, abs=1e-9)
    assert ev > 0.05


def test_expected_value_negative():
    ev = expected_value(0.30, 2.00)
    assert ev < 0
