import threading

import pytest

from app.jobs.base import JobContext, JobPayload
from app.jobs.queues import InlineJobQueue, ThreadJobQueue


def test_inline_queue_runs_handler_immediately(job_context: JobContext) -> None:
    received: list[JobPayload] = []
    queue = InlineJobQueue(job_context, {"demo": lambda _ctx, payload: received.append(payload)})

    queue.enqueue("demo", {"job_id": "123"})

    assert received == [{"job_id": "123"}]


def test_unknown_job_name_is_rejected_at_enqueue(job_context: JobContext) -> None:
    queue = InlineJobQueue(job_context, {})

    with pytest.raises(ValueError, match="Unknown job"):
        queue.enqueue("missing", {})


def test_handler_errors_are_contained(job_context: JobContext) -> None:
    def explode(_ctx: JobContext, _payload: JobPayload) -> None:
        raise RuntimeError("boom")

    queue = InlineJobQueue(job_context, {"explode": explode})

    queue.enqueue("explode", {})  # must not raise into the caller


def test_thread_queue_runs_jobs_in_background_and_shuts_down(job_context: JobContext) -> None:
    done = threading.Event()
    threads: list[str] = []

    def handler(_ctx: JobContext, _payload: JobPayload) -> None:
        threads.append(threading.current_thread().name)
        done.set()

    queue = ThreadJobQueue(job_context, {"work": handler}, max_workers=1)
    queue.enqueue("work", {})

    assert done.wait(timeout=5)
    assert threads[0].startswith("codesage-job")
    queue.shutdown()
    assert job_context.cancel_event.is_set()


def test_shutdown_signals_running_jobs_to_stop(job_context: JobContext) -> None:
    started, stopped = threading.Event(), threading.Event()

    def long_job(ctx: JobContext, _payload: JobPayload) -> None:
        started.set()
        if ctx.cancel_event.wait(timeout=10):
            stopped.set()

    queue = ThreadJobQueue(job_context, {"long": long_job}, max_workers=1)
    queue.enqueue("long", {})
    assert started.wait(timeout=5)

    queue.shutdown()

    assert stopped.is_set()
