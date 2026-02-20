"""Finite field arithmetic over F_p where p = 2^127 - 1 (Mersenne prime)."""

import rng

PRIME = (1 << 127) - 1  # 2^127 - 1


class FieldElement:
    """Element of the finite field F_p."""

    __slots__ = ('value',)

    def __init__(self, value: int):
        self.value = value % PRIME

    def __add__(self, other):
        if isinstance(other, int):
            other = FieldElement(other)
        return FieldElement((self.value + other.value) % PRIME)

    def __radd__(self, other):
        if isinstance(other, int):
            return FieldElement((other + self.value) % PRIME)
        return NotImplemented

    def __sub__(self, other):
        if isinstance(other, int):
            other = FieldElement(other)
        return FieldElement((self.value - other.value) % PRIME)

    def __rsub__(self, other):
        if isinstance(other, int):
            return FieldElement((other - self.value) % PRIME)
        return NotImplemented

    def __mul__(self, other):
        if isinstance(other, int):
            other = FieldElement(other)
        return FieldElement((self.value * other.value) % PRIME)

    def __rmul__(self, other):
        if isinstance(other, int):
            return FieldElement((other * self.value) % PRIME)
        return NotImplemented

    def __truediv__(self, other):
        if isinstance(other, int):
            other = FieldElement(other)
        return self * other.inverse()

    def __neg__(self):
        return FieldElement((-self.value) % PRIME)

    def __pow__(self, exp):
        if isinstance(exp, FieldElement):
            exp = exp.value
        return FieldElement(pow(self.value, exp, PRIME))

    def __eq__(self, other):
        if isinstance(other, int):
            return self.value == (other % PRIME)
        if isinstance(other, FieldElement):
            return self.value == other.value
        return NotImplemented

    def __hash__(self):
        return hash(self.value)

    def __repr__(self):
        return f"F({self.value})"

    def __bool__(self):
        return self.value != 0

    def inverse(self):
        """Multiplicative inverse via Fermat's little theorem: a^{p-2} mod p."""
        if self.value == 0:
            raise ZeroDivisionError("Cannot invert zero")
        return FieldElement(pow(self.value, PRIME - 2, PRIME))

    def to_int(self):
        """Return the integer value (valid for small values like bids in [0, 32))."""
        return self.value

    @staticmethod
    def random():
        """Return a random non-zero field element."""
        return FieldElement(rng.randbelow(PRIME - 1) + 1)

    @staticmethod
    def random_including_zero():
        """Return a random field element (may be zero)."""
        return FieldElement(rng.randbelow(PRIME))

    @staticmethod
    def zero():
        return FieldElement(0)

    @staticmethod
    def one():
        return FieldElement(1)
