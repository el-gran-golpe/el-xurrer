import asyncio

import pytest

from ai_content_pipeline.jobs.queue import Job, Queue


@pytest.mark.asyncio
async def test_concurrency_one_never_runs_two_jobs_of_the_same_type_at_once():
    queue = Queue()
    current = 0
    max_seen = 0

    async def handler(batch: list[Job]) -> None:
        nonlocal current, max_seen
        current += 1
        max_seen = max(max_seen, current)
        await asyncio.sleep(0.02)
        current -= 1

    queue.register("plan", handler, concurrency=1)
    for i in range(3):
        await queue.enqueue("plan", Job(id=f"plan-{i}"))

    await queue.run()

    assert max_seen == 1


@pytest.mark.asyncio
async def test_configured_concurrency_allows_jobs_to_overlap():
    queue = Queue()
    current = 0
    max_seen = 0

    async def handler(batch: list[Job]) -> None:
        nonlocal current, max_seen
        current += 1
        max_seen = max(max_seen, current)
        await asyncio.sleep(0.02)
        current -= 1

    queue.register("schedule", handler, concurrency=2)
    for i in range(4):
        await queue.enqueue("schedule", Job(id=f"schedule-{i}"))

    await queue.run()

    assert max_seen == 2


@pytest.mark.asyncio
async def test_a_failed_job_does_not_block_the_others():
    queue = Queue()
    processed: list[str] = []

    async def handler(batch: list[Job]) -> None:
        (job,) = batch
        if job.id == "boom":
            raise RuntimeError("failure")
        processed.append(job.id)

    queue.register("generate_image", handler, concurrency=1)
    for job_id in ["ok-1", "boom", "ok-2"]:
        await queue.enqueue("generate_image", Job(id=job_id))

    await queue.run()  # must not raise

    assert processed == ["ok-1", "ok-2"]


@pytest.mark.asyncio
async def test_batch_size_groups_already_pending_jobs_of_the_same_type():
    queue = Queue()
    seen_batches: list[list[str]] = []

    async def handler(batch: list[Job]) -> None:
        seen_batches.append([job.id for job in batch])

    queue.register("generate_image", handler, concurrency=1, batch_size=2)
    await queue.enqueue("generate_image", Job(id="a"))
    await queue.enqueue("generate_image", Job(id="b"))

    await queue.run()

    assert seen_batches == [["a", "b"]]


@pytest.mark.asyncio
async def test_run_waits_for_jobs_enqueued_by_a_handler_fan_out():
    queue = Queue()
    generated: list[str] = []

    async def generate_handler(batch: list[Job]) -> None:
        generated.append(batch[0].id)

    async def plan_handler(batch: list[Job]) -> None:
        for i in range(3):
            await queue.enqueue("generate_image", Job(id=f"image-{i}"))

    queue.register("plan", plan_handler, concurrency=1)
    queue.register("generate_image", generate_handler, concurrency=1)
    await queue.enqueue("plan", Job(id="plan-1"))

    await queue.run()

    assert sorted(generated) == ["image-0", "image-1", "image-2"]
