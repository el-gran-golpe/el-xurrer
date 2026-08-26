import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from loguru import logger

Handler = Callable[[list["Job"]], Awaitable[None]]


@dataclass
class Job:
    id: str
    payload: Any = field(default=None)


class Queue:
    """
    In-process job dispatcher: one asyncio.Queue per job type, each drained by
    its own fixed-size worker pool, so a job type stuck waiting for a scarce
    resource (e.g. a single local GPU, concurrency=1) never head-of-line
    blocks other types behind it.

    Handlers can enqueue further jobs (including of their own type) while
    `run()` is executing — `run()` only returns once every queue, including
    anything enqueued along the way, is fully drained. This is how fan-out
    (plan -> many generate_image) and fan-in (generate_image -> schedule)
    work: the handler itself calls `enqueue()` for the next step.
    """

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[Job]] = {}
        self._handlers: dict[str, Handler] = {}
        self._concurrency: dict[str, int] = {}
        self._batch_size: dict[str, int] = {}

    def register(
        self,
        job_type: str,
        handler: Handler,
        concurrency: int = 1,
        batch_size: int = 1,
    ) -> None:
        """
        `concurrency` is decided by the caller per job type, not by the
        Queue — e.g. a local ComfyUI backend registers `generate_image` with
        concurrency=1 because it's one GPU; a future backend for a different
        resource could register more. `batch_size` lets a handler receive up
        to N pending jobs of its type per call (unused today, batch_size=1;
        kept for a future backend that wants to group several jobs into one
        external submission).
        """
        self._queues[job_type] = asyncio.Queue()
        self._handlers[job_type] = handler
        self._concurrency[job_type] = concurrency
        self._batch_size[job_type] = batch_size

    async def enqueue(self, job_type: str, job: Job) -> None:
        await self._queues[job_type].put(job)

    async def run(self) -> None:
        workers = [
            asyncio.create_task(self._worker(job_type))
            for job_type in self._queues
            for _ in range(self._concurrency[job_type])
        ]
        await asyncio.gather(*(queue.join() for queue in self._queues.values()))
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

    async def _worker(self, job_type: str) -> None:
        queue = self._queues[job_type]
        handler = self._handlers[job_type]
        batch_size = self._batch_size[job_type]
        while True:
            batch = [await queue.get()]
            while len(batch) < batch_size:
                try:
                    batch.append(queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            try:
                await handler(batch)
            except Exception:
                logger.exception(
                    "Job handler for '{}' failed for batch {}",
                    job_type,
                    [job.id for job in batch],
                )
            finally:
                for _ in batch:
                    queue.task_done()
