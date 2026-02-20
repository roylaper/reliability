"""Tests for finite field arithmetic."""

import sys
sys.path.insert(0, '..')

from field import FieldElement, PRIME


def test_add():
    assert FieldElement(3) + FieldElement(4) == FieldElement(7)


def test_add_wrap():
    assert FieldElement(PRIME - 1) + FieldElement(2) == FieldElement(1)


def test_sub():
    assert FieldElement(10) - FieldElement(3) == FieldElement(7)


def test_sub_wrap():
    assert FieldElement(0) - FieldElement(1) == FieldElement(PRIME - 1)


def test_mul():
    assert FieldElement(5) * FieldElement(7) == FieldElement(35)


def test_div():
    a, b = FieldElement(5), FieldElement(7)
    assert (a / b) * b == a


def test_inverse():
    a = FieldElement(42)
    assert a * a.inverse() == FieldElement(1)


def test_inverse_one():
    assert FieldElement(1).inverse() == FieldElement(1)


def test_pow():
    assert FieldElement(2) ** 10 == FieldElement(1024)


def test_neg():
    a = FieldElement(5)
    assert a + (-a) == FieldElement(0)


def test_eq_int():
    assert FieldElement(42) == 42


def test_random_nonzero():
    for _ in range(10):
        r = FieldElement.random()
        assert r.value != 0


def test_zero_one():
    assert FieldElement.zero() == 0
    assert FieldElement.one() == 1
    assert FieldElement.zero() + FieldElement.one() == 1


def test_to_int():
    assert FieldElement(13).to_int() == 13


def test_bool():
    assert not bool(FieldElement.zero())
    assert bool(FieldElement.one())
