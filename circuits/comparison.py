"""Comparison circuit: greater-than on secret-shared bit vectors."""

from core.field import FieldElement
from protocols.mpc_arithmetic import MPCArithmetic


class ComparisonCircuit:
    """Compare two secret-shared values via their bit decompositions."""

    def __init__(self, mpc: MPCArithmetic):
        self.mpc = mpc

    async def greater_than(self, bits_a: list[FieldElement],
                           bits_b: list[FieldElement],
                           session_id: str) -> FieldElement:
        """Compute [a > b] given secret-shared bits (MSB-first).

        Uses prefix scan from MSB to LSB:
        - At each bit i, compute [gt_i] = a_i AND NOT b_i
        - Track running [eq_prefix] = product of eq at each position
        - result += eq_prefix * gt_i
        """
        k = len(bits_a)
        assert len(bits_b) == k

        prefix_eq = FieldElement.one()  # Public constant 1
        result = FieldElement.zero()

        for i in range(k):
            a_i = bits_a[i]
            b_i = bits_b[i]

            # [a_i * b_i] -- 1 multiplication
            ab = await self.mpc.multiply(a_i, b_i, f"{session_id}_ab_{i}")

            # [gt_i] = [a_i] - [a_i * b_i] = a_i AND (NOT b_i)
            gt_i = self.mpc.sub(a_i, ab)

            # [eq_i] = 1 - [a_i] - [b_i] + 2*[a_i*b_i]
            #        = XNOR(a_i, b_i) = 1 if a_i == b_i
            eq_i = self.mpc.add(
                self.mpc.sub(self.mpc.sub(FieldElement.one(), a_i), b_i),
                self.mpc.scalar_mul(FieldElement(2), ab)
            )

            # result += prefix_eq * gt_i -- 1 multiplication
            peq_gt = await self.mpc.multiply(prefix_eq, gt_i, f"{session_id}_pgt_{i}")
            result = self.mpc.add(result, peq_gt)

            # prefix_eq *= eq_i -- 1 multiplication
            prefix_eq = await self.mpc.multiply(prefix_eq, eq_i, f"{session_id}_peq_{i}")

        return result
