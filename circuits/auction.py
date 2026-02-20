"""Second-price auction circuit using MPC primitives.

Given active bids (from ACS, size >= n-f), determines the winner and computes
the second-highest bid. Only the winner learns the second price.
"""

import asyncio
from core.field import FieldElement
from protocols.mpc_arithmetic import MPCArithmetic
from circuits.bit_decomposition import BitDecomposition
from circuits.comparison import ComparisonCircuit
from protocols.output_privacy import OutputPrivacy
from sim.network import Network


class SecondPriceAuction:
    """Second-price auction computation for a single party."""

    NUM_BITS = 5  # Bids in [0, 32)

    def __init__(self, party_id: int, n: int, f: int, network: Network,
                 mpc: MPCArithmetic, bit_decomp: BitDecomposition,
                 comparison: ComparisonCircuit,
                 output_privacy: OutputPrivacy):
        self.party_id = party_id
        self.n = n
        self.f = f
        self.network = network
        self.mpc = mpc
        self.bit_decomp = bit_decomp
        self.comparison = comparison
        self.output_privacy = output_privacy

    async def run(self, bid_shares: dict[int, FieldElement],
                  active_set: set[int],
                  mask_shares: list[FieldElement] | None = None) -> FieldElement | None:
        """Run the second-price auction.

        bid_shares: {party_id: my share of that party's bid}
        active_set: parties whose bids are used (size >= n-f, from ACS)

        Returns: second_price if this party is the winner, 0 if not winner,
                 None if this party is not in the active set.
        """
        parties = sorted(active_set)
        m = len(parties)
        assert m >= self.n - self.f

        shares = [bid_shares[pid] for pid in parties]

        # Step 1: Bit decompose all bids
        bits = []
        for idx, pid in enumerate(parties):
            b = await self.bit_decomp.decompose(
                shares[idx], self.NUM_BITS, f"bid_{pid}")
            bits.append(b)

        # bits[i] is LSB-first; comparison needs MSB-first
        bits_msb = [list(reversed(b)) for b in bits]

        # Step 2: Pairwise comparisons
        # cmp[i][j] = [party_i > party_j] for i < j
        # cmp[j][i] = 1 - cmp[i][j]
        gt = {}  # (i, j) -> shared comparison result
        for i in range(m):
            for j in range(i + 1, m):
                gt[(i, j)] = await self.comparison.greater_than(
                    bits_msb[i], bits_msb[j], f"cmp_{parties[i]}_{parties[j]}")
                gt[(j, i)] = self.mpc.sub(FieldElement.one(), gt[(i, j)])

        # Step 3: is_max[i] = product of gt[(i, j)] for all j != i
        # Party i is the winner if it beats all others
        is_max = []
        for i in range(m):
            product = gt[(i, 0 if i != 0 else 1)]
            first = True
            for j in range(m):
                if j == i:
                    continue
                if first:
                    product = gt[(i, j)]
                    first = False
                else:
                    product = await self.mpc.multiply(
                        product, gt[(i, j)], f"max_{parties[i]}_{j}")
            is_max.append(product)

        # Step 4: is_min[i] = product of gt[(j, i)] for all j != i
        is_min = []
        for i in range(m):
            product = None
            for j in range(m):
                if j == i:
                    continue
                if product is None:
                    product = gt[(j, i)]
                else:
                    product = await self.mpc.multiply(
                        product, gt[(j, i)], f"min_{parties[i]}_{j}")
            is_min.append(product)

        # Step 5: is_second[i] for second-highest
        # For m=3: is_second = 1 - is_max - is_min
        # For m=4: need a different approach — second-highest means
        # exactly 1 party beats you (you beat m-2 others).
        # is_second[i] = product over j!=i of (gt[i,j] or gt[j,i] contributes to rank)
        # Simpler: rank[i] = sum over j!=i of gt[(j, i)] (number of parties that beat i)
        # second has rank = 1.
        # is_second[i] = (rank[i] == 1)
        # We can compute this as: rank_i * (2 - rank_i) * ... but that's complex.
        #
        # Alternative for small m: is_second[i] = 1 - is_max[i] - is_third_or_lower[i]
        # For m >= 3, a party with rank 1 beats exactly m-2 others.
        # Actually the simplest: compute for each party how many it beats.
        # wins[i] = sum_{j != i} gt[(i, j)]
        # is_second[i] = indicator(wins[i] == m-2)
        # In arithmetic: for m=3, is_second = wins*(wins-1)/2 when wins=1 -> 0, wins=2 -> 1? No.
        # wins=1 means second place (beats exactly 1 out of 2 others).
        # Actually wins[i] = number of parties i beats.
        # max has wins = m-1, second has wins = m-2, etc.
        #
        # For general m, to check wins[i] == m-2:
        # We construct the polynomial that is 1 at m-2 and 0 at all other possible values.
        # Possible wins values: 0, 1, ..., m-1.
        # indicator(w == m-2) = product_{k != m-2, k in {0..m-1}} (w - k) / ((m-2) - k)
        # This can be computed, but requires multiplications.
        #
        # Simpler for m=3 or m=4:
        if m == 3:
            is_second = [
                self.mpc.sub(self.mpc.sub(FieldElement.one(), is_max[i]), is_min[i])
                for i in range(m)
            ]
        elif m == 4:
            # wins[i] = sum of gt[(i, j)] for j != i
            wins = []
            for i in range(m):
                w = FieldElement.zero()
                for j in range(m):
                    if j != i:
                        w = self.mpc.add(w, gt[(i, j)])
                wins.append(w)
            # is_second[i] = indicator(wins[i] == m-2 = 2)
            # = wins[i] * (wins[i] - 1) / 2 * (3 - wins[i])  ... no
            # indicator(w == 2) for w in {0,1,2,3}:
            # = w*(w-1)*(w-3) / (2*(2-1)*(2-3)) = w*(w-1)*(w-3) / (2*1*(-1)) = w*(w-1)*(w-3) / (-2)
            # Let's verify: w=0 -> 0, w=1 -> 0, w=2 -> 2*1*(-1)/(-2) = 1, w=3 -> 3*2*0/(-2) = 0. Correct!
            inv_neg2 = FieldElement(-2).inverse()
            is_second = []
            for i in range(m):
                w = wins[i]
                w_minus_1 = self.mpc.sub(w, FieldElement.one())
                w_minus_3 = self.mpc.sub(w, FieldElement(3))
                # w * (w-1)
                t1 = await self.mpc.multiply(w, w_minus_1, f"sec_t1_{parties[i]}")
                # t1 * (w-3)
                t2 = await self.mpc.multiply(t1, w_minus_3, f"sec_t2_{parties[i]}")
                # t2 / (-2)
                is_second.append(self.mpc.scalar_mul(inv_neg2, t2))
        else:
            raise ValueError(f"Unsupported active set size: {m}")

        # Step 6: Compute second price value
        # [sp] = sum_i [bid_i] * [is_second_i]
        sp_terms = []
        for i in range(m):
            term = await self.mpc.multiply(shares[i], is_second[i], f"sp_{parties[i]}")
            sp_terms.append(term)
        second_price = sp_terms[0]
        for i in range(1, m):
            second_price = self.mpc.add(second_price, sp_terms[i])

        # Step 7: Output masking — each party gets is_max * second_price or 0
        outputs = {}
        for idx, pid in enumerate(parties):
            outputs[pid] = await self.mpc.multiply(
                is_max[idx], second_price, f"out_{pid}")

        # Step 8: Output privacy via mask-and-open
        if self.party_id in active_set:
            my_result = FieldElement.zero()
            for idx, pid in enumerate(parties):
                # Use preprocessed mask share if available, else zero mask
                mask = mask_shares[idx] if mask_shares and idx < len(mask_shares) else FieldElement.zero()
                result = await self.output_privacy.reveal_to_owner(
                    outputs[pid], pid, mask, f"output_{pid}")
                if pid == self.party_id:
                    my_result = result
            return my_result

        return None
