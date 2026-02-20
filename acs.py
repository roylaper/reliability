"""Agreement on Common Set for omission failure model.

Determines which parties' CSS sharings to include in the computation.
Output: set of at least n-f dealer IDs whose sharings are accepted.
"""

import asyncio
from network import Network, Message


class ACSProtocol:
    """ACS protocol instance for a single party."""

    def __init__(self, party_id: int, n: int, f: int, network: Network):
        self.party_id = party_id
        self.n = n
        self.f = f
        self.network = network

        self._votes: dict[int, set[int]] = {}  # voter -> set of dealers they accepted
        self._result: set[int] | None = None
        self._done = asyncio.Event()

    async def run(self, accepted_dealers: set[int]) -> set[int]:
        """Run ACS. accepted_dealers = set of dealer IDs whose CSS we accepted.

        Returns the agreed-upon set of dealer IDs (size >= n-f).
        """
        # Broadcast our vote
        msg = Message("ACS_VOTE", self.party_id, {
            "accepted": list(accepted_dealers),
        }, "acs")
        await self.network.broadcast(self.party_id, msg)

        # Record own vote
        self._votes[self.party_id] = accepted_dealers

        # Wait for result
        await self._check_result()
        await self._done.wait()
        return self._result

    async def handle_vote(self, msg: Message):
        """Handle incoming ACS_VOTE message."""
        voter = msg.sender
        accepted = set(msg.payload["accepted"])
        self._votes[voter] = accepted
        await self._check_result()

    async def _check_result(self):
        """Check if we can determine the common set."""
        # Need votes from at least n-f parties
        if len(self._votes) < self.n - self.f:
            return

        # A dealer is confirmed if at least f+1 parties voted for it
        confirmed = set()
        for dealer_id in range(1, self.n + 1):
            vote_count = sum(
                1 for voter_set in self._votes.values()
                if dealer_id in voter_set
            )
            if vote_count >= self.f + 1:
                confirmed.add(dealer_id)

        if len(confirmed) >= self.n - self.f:
            self._result = confirmed
            self._done.set()
