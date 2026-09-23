"""Background jobs.

API requests never clone or index inline. They record a job in the database and
hand its id to a `JobQueue`; a worker runs the named handler later.

Today the queue is an in-process thread pool (`ThreadJobQueue`). To move to
Celery/RQ, implement `JobQueue.enqueue` with the broker client (e.g.
`celery_app.send_task(name, kwargs=payload)`) and have the worker process call
`run_registered_job(name, payload, context)` — handlers, payloads and the job
table stay the same.
"""
