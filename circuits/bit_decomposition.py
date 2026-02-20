"""Bit decomposition: convert secret-shared value to secret-shared bits.

Uses pre-generated random bit sharings (from preprocessing) + bit subtraction circuit.
"""

from core import rng
from core.field import FieldElement, PRIME
from core.polynomial import Polynomial
from protocols.mpc_arithmetic import MPCArithmetic


def preprocess_random_bit_sharings(n: int, f: int, count: int) -> list[dict[int, FieldElement]]:
    """Preprocessing: generate `count` random bit sharings.

    Each sharing is a degree-f polynomial with p(0) ∈ {0, 1}.
    Returns list of dicts: [{party_id: share}, ...].

    In a real protocol, this would use beacon + CSS for joint generation.
    Here we simulate the ideal preprocessing functionality.
    """
    result = []
    for _ in range(count):
        bit = rng.randbelow(2)
        poly = Polynomial.random(degree=f, constant=FieldElement(bit))
        shares = {i: poly.evaluate(FieldElement(i)) for i in range(1, n + 1)}
        result.append(shares)
    return result


class BitDecomposition:
    """Decompose secret-shared values into secret-shared bits."""

    def __init__(self, party_id: int, n: int, f: int, mpc: MPCArithmetic):
        self.party_id = party_id
        self.n = n
        self.f = f
        self.mpc = mpc
        self._random_bits: list[FieldElement] = []  # Queue of pre-generated shared bits

    def load_random_bits(self, bit_sharings: list[dict[int, FieldElement]]):
        """Load pre-generated random bit shares for this party."""
        self._random_bits = [bs[self.party_id] for bs in bit_sharings]

    def _consume_random_bit(self) -> FieldElement:
        """Get the next pre-generated random bit share."""
        if not self._random_bits:
            raise RuntimeError("Ran out of pre-generated random bits")
        return self._random_bits.pop(0)

    async def decompose(self, shared_value: FieldElement, num_bits: int,
                        session_id: str) -> list[FieldElement]:
        """Decompose [x] (where x < 2^num_bits) into shared bits [b_0]...[b_{k-1}].

        Method:
        1. Consume num_bits pre-generated random shared bits [r_0]..[r_{k-1}]
        2. Compute [r] = sum r_i * 2^i
        3. Open y = x + r (no field wraparound since x,r < 2^k << p)
        4. Compute bits of x = y - r via bit subtraction circuit
        """
        # Step 1: Get random shared bits
        random_bits = [self._consume_random_bit() for _ in range(num_bits)]

        # Step 2: Compute [r] = sum r_i * 2^i
        r_share = FieldElement.zero()
        for i, rb in enumerate(random_bits):
            r_share = self.mpc.add(r_share, self.mpc.scalar_mul(FieldElement(1 << i), rb))

        # Step 3: Open y = x + r
        masked = self.mpc.add(shared_value, r_share)
        y = await self.mpc.open_value(masked, f"{session_id}_mask")

        # Step 4: Bit subtraction: compute bits of (y - r) where y is public
        y_int = y.to_int()
        # y could be up to 2 * 2^num_bits - 2, need num_bits + 1 bits for the public value
        y_bits = [(y_int >> i) & 1 for i in range(num_bits + 1)]

        result_bits = await self._bit_subtraction(y_bits, random_bits, session_id)
        return result_bits[:num_bits]

    async def _bit_subtraction(self, public_bits: list[int],
                                shared_bits: list[FieldElement],
                                session_id: str) -> list[FieldElement]:
        """Compute bits of (public - shared) via ripple-borrow subtraction.

        public_bits[i] are plain integers 0/1.
        shared_bits[i] are secret-shared bits.
        Returns secret-shared result bits.
        """
        borrow = FieldElement.zero()  # Initially no borrow
        result = []

        for i in range(len(shared_bits)):
            y_i = public_bits[i]
            r_i = shared_bits[i]

            # XOR(y_i, r_i): y_i is public, so this is local
            if y_i == 0:
                t1 = r_i  # 0 XOR r_i = r_i
            else:
                t1 = self.mpc.sub(FieldElement.one(), r_i)  # 1 XOR r_i = 1 - r_i

            # XOR(t1, borrow) = t1 + borrow - 2*t1*borrow (1 multiplication)
            t1_times_borrow = await self.mpc.multiply(
                t1, borrow, f"{session_id}_xor_{i}")
            x_i = self.mpc.sub(
                self.mpc.add(t1, borrow),
                self.mpc.scalar_mul(FieldElement(2), t1_times_borrow)
            )
            result.append(x_i)

            # Borrow: borrow_{i+1} = (r_i AND borrow) OR (NOT_y_i AND (r_i XOR borrow))
            # = r_i*borrow + (1-y_i)*(r_i + borrow - 2*r_i*borrow)
            r_times_borrow = await self.mpc.multiply(
                r_i, borrow, f"{session_id}_borrow_{i}")
            not_y = 1 - y_i  # public scalar
            xor_rb = self.mpc.sub(
                self.mpc.add(r_i, borrow),
                self.mpc.scalar_mul(FieldElement(2), r_times_borrow)
            )
            borrow = self.mpc.add(
                r_times_borrow,
                self.mpc.scalar_mul(FieldElement(not_y), xor_rb)
            )

        return result
