import pytest

from hr_agents.providers.queue import MemoryQueueBackend, QueueMessage
from hr_agents.services.worker import Handler, Worker, WorkerConfig

TOPIC = "tests.work"


@pytest.fixture
def queue() -> MemoryQueueBackend:
    return MemoryQueueBackend()


def make_worker(queue: MemoryQueueBackend, handler: Handler, **config_overrides: object) -> Worker:
    defaults: dict[str, object] = {"topic": TOPIC, "max_attempts": 3, "batch_size": 5}
    defaults.update(config_overrides)
    return Worker(queue, handler, config=WorkerConfig(**defaults))  # type: ignore[arg-type]


async def test_worker_processes_success(queue: MemoryQueueBackend) -> None:
    seen: list[dict] = []

    async def handler(message: QueueMessage) -> None:
        seen.append(message.payload)

    await queue.publish(TOPIC, {"n": 1})
    await queue.publish(TOPIC, {"n": 2})

    worker = make_worker(queue, handler)
    processed = await worker.run_once()

    assert processed == 2
    assert worker.stats.processed == 2
    assert worker.stats.failed == 0
    assert {item["n"] for item in seen} == {1, 2}
    stats = await queue.stats(TOPIC)
    assert stats.pending == 0
    assert stats.inflight == 0


async def test_worker_requeues_then_succeeds(queue: MemoryQueueBackend) -> None:
    attempts: list[int] = []

    async def handler(message: QueueMessage) -> None:
        attempts.append(message.attempts)
        if message.attempts == 0:
            raise RuntimeError("transient")

    await queue.publish(TOPIC, {"n": 1})
    worker = make_worker(queue, handler)

    await worker.run_once()  # fails once, requeued
    await worker.run_once()  # succeeds on second attempt

    assert attempts == [0, 1]
    assert worker.stats.requeued == 1
    assert worker.stats.processed == 1


async def test_worker_dead_letters_after_max_attempts(queue: MemoryQueueBackend) -> None:
    async def handler(message: QueueMessage) -> None:
        raise RuntimeError("permanent")

    await queue.publish(TOPIC, {"n": 1})
    worker = make_worker(queue, handler, max_attempts=3)

    await worker.run_once()
    await worker.run_once()
    await worker.run_once()

    assert worker.stats.dead_lettered == 1
    dead = await queue.dead_letters(TOPIC)
    assert len(dead) == 1
    assert any("permanent" in error for error in worker.stats.errors)


async def test_worker_batch_limit(queue: MemoryQueueBackend) -> None:
    processed: list[str] = []

    async def handler(message: QueueMessage) -> None:
        processed.append(message.id)

    for index in range(5):
        await queue.publish(TOPIC, {"n": index})

    worker = make_worker(queue, handler, batch_size=2)
    first = await worker.run_once()
    second = await worker.run_once()

    assert first == 2
    assert second == 2
    assert len(processed) == 4


def test_worker_requires_config(queue: MemoryQueueBackend) -> None:
    async def handler(message: QueueMessage) -> None:
        return None

    with pytest.raises(ValueError, match="WorkerConfig"):
        Worker(queue, handler)
