"""Randomness beacon: provides random field elements when f+1 parties request."""

import asyncio
from core.field import FieldElement


class RandomnessBeacon:
    """Simulates an ideal randomness beacon.

    Releases random FieldElement rho_i when at least `threshold` parties
    request beacon index i.
    """

    def __init__(self, threshold: int = 2):
        self.threshold = threshold
        self._requests: dict[int, set[int]] = {}
        self._values: dict[int, FieldElement] = {}
        self._events: dict[int, asyncio.Event] = {}
        self._lock = asyncio.Lock()
        self.invocations = 0

    async def request(self, beacon_index: int, party_id: int) -> FieldElement:
        """Request beacon value rho_{beacon_index}. Blocks until threshold met."""
        async with self._lock:
            if beacon_index not in self._requests:
                self._requests[beacon_index] = set()
                self._events[beacon_index] = asyncio.Event()
            self._requests[beacon_index].add(party_id)
            if len(self._requests[beacon_index]) >= self.threshold:
                if beacon_index not in self._values:
                    self._values[beacon_index] = FieldElement.random()
                    self.invocations += 1
                self._events[beacon_index].set()

        await self._events[beacon_index].wait()
        return self._values[beacon_index]
 