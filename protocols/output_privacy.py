"""Output privacy via mask-and-open + private unmask.

For each party's output [o_i]:
1. Compute [y_i] = [o_i] + [mask_i] (local addition)
2. Public open y_i (all parties reconstruct)
3. Send mask shares privately to owner i
4. Owner computes o_i = y_i - mask_i
"""

import asyncio
from core.field import FieldElement
from core.polynomial import Polynomial
from sim.network import Network, Message
from protocols.mpc_arithmetic import MPCArithmetic


class OutputPrivacy:
    """Mask-and-open output privacy module."""

    def __init__(self, party_id: int, n: int, f: int,
                 network: Network, mpc: MPCArithmetic):
        self.party_id = party_id
        self.n = n
        self.f = f
        self.network = network
        self.mpc = mpc

        self._mask_shares: dict[str, dict[int, FieldElement]] = {}

    async def reveal_to_owner(self, output_share: FieldElement,
                               owner_party_id: int,
                               mask_share: FieldElement,
                               session_id: str) -> FieldElement:
        """Reveal output to owner only using mask-and-open.

        Returns: output value for owner, 0 for non-owners.
        """
        # Step 1: Compute masked value [y] = [output] + [mask] (local)
        masked_share = self.mpc.add(output_share, mask_share)

        # Step 2: Public open y (all reconstruct y)
        y = await self.mpc.open_value(masked_share, f"{session_id}_pub")

        # Step 3: Send mask share privately to owner
        mask_key = f"mask_{session_id}"
        if mask_key not in self._mask_shares:
            self._mask_shares[mask_key] = {}

        if self.party_id == owner_party_id:
            # Record own mask share
            self._mask_shares[mask_key][self.party_id] = mask_share
        else:
            # Send mask share to owner
            msg = Message("MASK_SHARE", self.party_id, {
                "session_id": session_id,
                "point": self.party_id,
                "share_value": mask_share.value,
            }, session_id)
            await self.network.send(self.party_id, owner_party_id, msg)

        # Step 4: Owner reconstructs mask and computes output
        if self.party_id == owner_party_id:
            while len(self._mask_shares[mask_key]) < self.f + 1:
                await asyncio.sleep(0.001)

            points = [
                (FieldElement(pid), share)
                for pid, share in self._mask_shares[mask_key].items()
            ]
            mask = Polynomial.interpolate_at_zero(points[:self.f + 1])
            output = y - mask
            return output

        return FieldElement.zero()

    async def handle_mask_share(self, msg: Message):
        """Handle incoming MASK_SHARE message."""
        sid = msg.payload["session_id"]
        mask_key = f"mask_{sid}"
        if mask_key not in self._mask_shares:
            self._mask_shares[mask_key] = {}
        point = msg.payload["point"]
        share_val = FieldElement(msg.payload["share_value"])
        self._mask_shares[mask_key][point] = share_val
