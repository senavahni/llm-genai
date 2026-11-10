"""Semaphore dengan antrean prioritas (LGW-V1-04): slot yang dilepas diberikan ke penunggu
berprioritas tertinggi (angka kecil), FIFO untuk prioritas sama. Dipakai DeviceManager agar
request `interactive` dilayani sebelum batch `bulk` berikutnya."""

import asyncio
import heapq
import itertools

INTERACTIVE = 0
BULK = 1
PRIORITIES = {"interactive": INTERACTIVE, "bulk": BULK}


class PrioritySemaphore:
    def __init__(self, value: int) -> None:
        self._value = value  # slot bebas (dibaca LoadedModel.active)
        self._waiters: list[tuple[int, int, asyncio.Future[None]]] = []
        self._seq = itertools.count()

    def locked(self) -> bool:
        return self._value == 0 or any(not f.done() for _, _, f in self._waiters)

    def waiting(self, priority: int | None = None) -> int:
        return sum(
            1 for p, _, f in self._waiters if not f.done() and (priority is None or p == priority)
        )

    async def acquire(self, priority: int = INTERACTIVE) -> None:
        if not self.locked():
            self._value -= 1
            return
        fut: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        heapq.heappush(self._waiters, (priority, next(self._seq), fut))
        try:
            await fut
        except BaseException:
            if fut.done() and not fut.cancelled():
                self.release()  # slot sudah diberikan tetapi penunggu batal: kembalikan
            raise

    def release(self) -> None:
        while self._waiters:
            _, _, fut = heapq.heappop(self._waiters)
            if not fut.done():
                fut.set_result(None)  # slot langsung berpindah tangan
                return
        self._value += 1
