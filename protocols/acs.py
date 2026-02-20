"""Agreement on Common Set (ACS) using RBC + BA.

Fully event-driven, no timeouts:
1. Each party RBC-broadcasts its proposal
2. As RBC instances deliver, start BA with input 1
3. Once n-f BA instances decide 1, input 0 for all remaining
4. Wait for all BA instances to finish
5. Return {j : BA_j decided 1}
"""

import asyncio
from sim.network import Network, Message
from sim.beacon import RandomnessBeacon
from protocols.rbc import RBCProtocol
from protocols.ba import BAProtocol


class ACSProtocol:
    """ACS built from RBC + BA. Fully event-driven."""

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

        No timeouts. Progress is driven by RBC deliveries and BA decisions.
        """
        # Step 1: RBC-broadcast own proposal
        tag = f"acs_propose_{self.party_id}"
        await self.rbc.broadcast(tag, list(accepted_dealers))

        # Step 2: Track which RBC proposals have been delivered
        delivered = set()
        delivered.add(self.party_id)  # Own proposal is trivially delivered

        # BA results and coordination
        ba_decided_1_count = 0
        ba_decided_1_enough = asyncio.Event()  # fires when n-f BA decide 1
        ba_started: set[int] = set()
        ba_results: dict[int, int] = {}
        all_ba_done = asyncio.Event()

        lock = asyncio.Lock()

        async def on_ba_result(j: int, value: int):
            nonlocal ba_decided_1_count
            async with lock:
                ba_results[j] = value
                if value == 1:
                    ba_decided_1_count += 1
                    if ba_decided_1_count >= self.n - self.f:
                        ba_decided_1_enough.set()
                if len(ba_results) == self.n:
                    all_ba_done.set()

        async def run_ba_for(j: int, estimate: int):
            result = await self.ba.run(ba_index=j, initial_estimate=estimate)
            await on_ba_result(j, result)

        # Step 3: Watch for RBC deliveries and start BA with input 1
        async def watch_rbc(pid: int):
            ptag = f"acs_propose_{pid}"
            val = await self.rbc.wait_deliver(pid, ptag)
            async with lock:
                delivered.add(pid)
                if pid not in ba_started:
                    ba_started.add(pid)
                    asyncio.create_task(run_ba_for(pid, 1))

        # Start watching all other parties' RBC proposals
        for pid in range(1, self.n + 1):
            if pid != self.party_id:
                asyncio.create_task(watch_rbc(pid))

        # Start BA for own proposal immediately with input 1
        # (our own RBC trivially delivers to us)
        if self.party_id in accepted_dealers:
            ba_started.add(self.party_id)
            asyncio.create_task(run_ba_for(self.party_id, 1))

        # Step 4: Once n-f BA instances decide 1, input 0 for all remaining
        await ba_decided_1_enough.wait()

        async with lock:
            for j in range(1, self.n + 1):
                if j not in ba_started:
                    ba_started.add(j)
                    asyncio.create_task(run_ba_for(j, 0))

        # Step 5: Wait for all BA instances to complete
        await all_ba_done.wait()

        # Step 6: Return agreed set
        return {j for j, v in ba_results.items() if v == 1}
