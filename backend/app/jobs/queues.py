from concurrent.futures import ThreadPoolExecutor

from app.jobs.base import JobPayload, JobQueue, run_registered_job


class InlineJobQueue(JobQueue):
    """Runs each job immediately in the caller's thread. For tests and debugging."""

    def _submit(self, name: str, payload: JobPayload) -> None:
        run_registered_job(name, payload, self.context, self.handlers)


class ThreadJobQueue(JobQueue):
    """Runs jobs on a bounded pool of worker threads inside the API process.

    Limits: jobs live in memory, so they only run while this process is up (jobs
    interrupted by a restart are marked failed at the next startup), and it
    assumes a single API process. A broker-backed queue removes both limits.
    """

    def __init__(self, *args, max_workers: int, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="codesage-job"
        )

    def _submit(self, name: str, payload: JobPayload) -> None:
        self._executor.submit(run_registered_job, name, payload, self.context, self.handlers)

    def shutdown(self) -> None:
        super().shutdown()
        # Running jobs notice the cancel event within about a second; jobs that
        # never started are dropped and recovered as failed at the next startup.
        self._executor.shutdown(wait=True, cancel_futures=True)
