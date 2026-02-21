"""Agreement on Common Set (ACS) using RBC + BA.

Fully event-driven, no timeouts. Supports instance_id for namespacing
(allows running multiple ACS instances, e.g. per-gate).
"""

import asyncio
from sim.network import Network
from sim.beacon import RandomnessBeacon
from protocols.rbc import RBCProtocol
from protocols.ba import BAProtocol


class ACSProtocol:
    """ACS built from RBC + BA. Fully event-driven, instance-namespaced."""

    def __init__(self, party_id: int, n: int, f: int,
                 network: Network, beacon: RandomnessBeacon,
                 rbc: RBCProtocol, ba: BAProtocol):
        self.party_id = party_id
        self.n = n
        self.f = f
        self.network = network
        self.rbc = rbc
        self.ba = ba

    async def run(self, accepted_dealers: set[int],
                  instance_id: str = "main") -> set[int]:
        """Run ACS. Returns agreed-upon set of dealer IDs (size >= n-f).

        instance_id namespaces all RBC/BA to avoid collisions when running
        multiple ACS instances (e.g. per multiplication gate).
        """
        # Step 1: RBC-broadcast own proposal
        tag = f"acs:{instance_id}:propose:{self.party_id}"
        await self.rbc.broadcast(tag, list(accepted_dealers))

        # Coordination state
        delivered = {self.party_id}
        ba_started: set[int] = set()
        ba_results: dict[int, int] = {}
        decided_1_count = 0
        decided_1_enough = asyncio.Event()
        all_ba_done = asyncio.Event()
        lock = asyncio.Lock()

        async def on_ba_result(j: int, value: int):
            nonlocal decided_1_count
            async with lock:
                ba_results[j] = value
                if value == 1:
                    decided_1_count += 1
                    if decided_1_count >= self.n - self.f:
                        decided_1_enough.set()
                if len(ba_results) == self.n:
                    all_ba_done.set()

        async def run_ba_for(j: int, estimate: int):
            ba_key = f"acs:{instance_id}:ba:{j}"
            result = await self.ba.run(ba_key, estimate)
            await on_ba_result(j, result)

        # Step 2: Watch for RBC deliveries, start BA with input 1
        async def watch_rbc(pid: int):
            ptag = f"acs:{instance_id}:propose:{pid}"
            await self.rbc.wait_deliver(pid, ptag)
            async with lock:
                delivered.add(pid)
                if pid not in ba_started:
                    ba_started.add(pid)
                    asyncio.create_task(run_ba_for(pid, 1))

        for pid in range(1, self.n + 1):
            if pid != self.party_id:
                asyncio.create_task(watch_rbc(pid))

        # Start BA for own proposal with input 1
        if self.party_id in accepted_dealers:
            ba_started.add(self.party_id)
            asyncio.create_task(run_ba_for(self.party_id, 1))

        # Step 3: Once n-f BAs decide 1, input 0 for remaining
        await decided_1_enough.wait()
        async with lock:
            for j in range(1, self.n + 1):
                if j not in ba_started:
                    ba_started.add(j)
                    asyncio.create_task(run_ba_for(j, 0))

        # Step 4: Wait for all BAs
        await all_ba_done.wait()

        return {j for j, v in ba_results.items() if v == 1}
