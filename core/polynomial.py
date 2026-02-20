"""Polynomial operations and Lagrange interpolation over F_p."""

from core.field import FieldElement


class Polynomial:
    """Polynomial over F_p. coeffs[0] = constant term."""

    def __init__(self, coeffs: list[FieldElement]):
        self.coeffs = coeffs

    @property
    def degree(self) -> int:
        return len(self.coeffs) - 1

    def evaluate(self, x: FieldElement) -> FieldElement:
        """Evaluate polynomial at x using Horner's method."""
        if not isinstance(x, FieldElement):
            x = FieldElement(x)
        result = FieldElement.zero()
        for coeff in reversed(self.coeffs):
            result = result * x + coeff
        return result

    @staticmethod
    def random(degree: int, constant: FieldElement) -> 'Polynomial':
        """Random polynomial of given degree with p(0) = constant."""
        coeffs = [constant]
        for _ in range(degree):
            coeffs.append(FieldElement.random())
        return Polynomial(coeffs)

    @staticmethod
    def interpolate_at_zero(points: list[tuple[FieldElement, FieldElement]]) -> FieldElement:
        """Lagrange interpolation evaluated at x=0.

        points: list of (x_i, y_i) pairs.
        Returns p(0) = sum_i y_i * lambda_i where lambda_i = prod_{j!=i} (-x_j)/(x_i - x_j).
        """
        n = len(points)
        result = FieldElement.zero()
        for i in range(n):
            xi, yi = points[i]
            numerator = FieldElement.one()
            denominator = FieldElement.one()
            for j in range(n):
                if i == j:
                    continue
                xj = points[j][0]
                numerator = numerator * (-xj)
                denominator = denominator * (xi - xj)
            lambda_i = numerator / denominator
            result = result + yi * lambda_i
        return result


def lagrange_coefficients_at_zero(x_values: list[FieldElement]) -> list[FieldElement]:
    """Precompute Lagrange basis coefficients at x=0 for given x-coordinates.

    Returns lambda_i = prod_{j!=i} (-x_j) / (x_i - x_j) for each i.
    """
    n = len(x_values)
    lambdas = []
    for i in range(n):
        numerator = FieldElement.one()
        denominator = FieldElement.one()
        for j in range(n):
            if i == j:
                continue
            numerator = numerator * (-x_values[j])
            denominator = denominator * (x_values[i] - x_values[j])
        lambdas.append(numerator / denominator)
    return lambdas
