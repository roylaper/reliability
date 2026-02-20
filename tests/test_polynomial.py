"""Tests for polynomial operations and Lagrange interpolation."""

from core.field import FieldElement
from core.polynomial import Polynomial, lagrange_coefficients_at_zero


def test_evaluate_constant():
    p = Polynomial([FieldElement(42)])
    assert p.evaluate(FieldElement(0)) == 42
    assert p.evaluate(FieldElement(99)) == 42

def test_evaluate_linear():
    p = Polynomial([FieldElement(3), FieldElement(2)])
    assert p.evaluate(FieldElement(0)) == 3
    assert p.evaluate(FieldElement(1)) == 5
    assert p.evaluate(FieldElement(5)) == 13

def test_evaluate_quadratic():
    p = Polynomial([FieldElement(1), FieldElement(0), FieldElement(1)])
    assert p.evaluate(FieldElement(0)) == 1
    assert p.evaluate(FieldElement(3)) == 10

def test_random_polynomial():
    p = Polynomial.random(degree=1, constant=FieldElement(42))
    assert p.evaluate(FieldElement(0)) == 42
    assert p.degree == 1

def test_interpolate_at_zero_degree1():
    secret = FieldElement(42)
    p = Polynomial.random(degree=1, constant=secret)
    pts = [(FieldElement(1), p.evaluate(FieldElement(1))),
           (FieldElement(2), p.evaluate(FieldElement(2)))]
    assert Polynomial.interpolate_at_zero(pts) == secret

def test_interpolate_at_zero_degree1_other_points():
    secret = FieldElement(99)
    p = Polynomial.random(degree=1, constant=secret)
    pts = [(FieldElement(3), p.evaluate(FieldElement(3))),
           (FieldElement(4), p.evaluate(FieldElement(4)))]
    assert Polynomial.interpolate_at_zero(pts) == secret

def test_interpolate_at_zero_degree2():
    secret = FieldElement(7)
    p = Polynomial([FieldElement(7), FieldElement(3), FieldElement(5)])
    pts = [(FieldElement(i), p.evaluate(FieldElement(i))) for i in range(1, 4)]
    assert Polynomial.interpolate_at_zero(pts) == secret

def test_interpolate_overdetermined():
    secret = FieldElement(42)
    p = Polynomial.random(degree=1, constant=secret)
    pts = [(FieldElement(i), p.evaluate(FieldElement(i))) for i in range(1, 5)]
    assert Polynomial.interpolate_at_zero(pts) == secret

def test_lagrange_coefficients():
    x_vals = [FieldElement(1), FieldElement(2)]
    lambdas = lagrange_coefficients_at_zero(x_vals)
    assert lambdas[0] == FieldElement(2)
    assert lambdas[1] == FieldElement(-1)
