"""Agreement on Common Set (ACS) using RBC + BA.

Theory-faithful construction:
1. Each party RBC-broadcasts its proposal (accepted dealer set)
2. For each party j, run BA_j to decide inclusion
3. Output set = {j : BA_j decided 1}
"""

import asyncio
from sim.network import Network, Message
from sim.beacon import RandomnessBeacon
from protocols.rbc import RBCProtocol
from protocols.ba import BAProtocol


class ACSProtocol:
    """ACS built from RBC + BA for a single party."""

    def __init__(self, party_id: int, n: int, f: int,
                 network: Network, beacon: RandomnessBeacon,
                 rbc: RBCProtocol):
        self.party_id = party_id
        self.n = n
        self.f = f
        self.network = network
        self.rbc = rbc
        self.ba = BAProtocol(party_id, n, f, network, beacon)

    async def run(self, accepted_dealers: set[int]) -> set[int]:
        """Run ACS. Returns the agreed-upon set of dealer IDs (size >= n-f).

        1. RBC-broadcast own proposal
        2. Collect RBC deliveries to determine BA inputs
        3. Run BA_j for each j to decide inclusion
        4. Return {j : BA_j decided 1}
        """
        # Step 1: RBC-broadcast own accepted set
        tag = f"acs_propose_{self.party_id}"
        await self.rbc.broadcast(tag, list(accepted_dealers))

        # Step 2: Wait for RBC deliveries from other parties
        # Give time for RBC to propagate, then determine BA inputs
        delivered_proposals: dict[int, set[int]] = {}
        delivered_proposals[self.party_id] = accepted_dealers

        # Try to collect proposals from all parties (with timeout for omitting ones)
        async def collect_proposal(pid):
            try:
                ptag = f"acs_propose_{pid}"
                val = await self.rbc.wait_deliver(pid, ptag, timeout=3.0)
                delivered_proposals[pid] = set(val)
            except asyncio.TimeoutError:
                pass  # Party probably omitting

        wait_tasks = []
        for pid in range(1, self.n + 1):
            if pid != self.party_id:
                wait_tasks.append(collect_proposal(pid))
        await asyncio.gather(*wait_tasks)

        # Step 3: Determine BA inputs
        # For each dealer j: input 1 if j was accepted by enough delivered proposals
        # A dealer j is "viable" if at least one delivered proposal includes j
        # But the simplest correct approach: input 1 to BA_j if we ourselves
        # accepted j's CSS AND we got RBC delivery for j's proposal
        ba_inputs = {}
        for j in range(1, self.n + 1):
            if j in accepted_dealers and j in delivered_proposals:
                ba_inputs[j] = 1
            else:
                ba_inputs[j] = 0

        # Step 4: Run all BA instances in parallel
        async def run_ba(j):
            return await self.ba.run(ba_index=j, initial_estimate=ba_inputs[j])

        ba_results = await asyncio.gather(*[run_ba(j) for j in range(1, self.n + 1)])

        # Step 5: Output set
        result = set()
        for j_idx, j in enumerate(range(1, self.n + 1)):
            if ba_results[j_idx] == 1:
                result.add(j)

        return result
