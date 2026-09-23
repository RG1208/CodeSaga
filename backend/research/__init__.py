"""Research tooling: retrieval evaluation, kept out of the application.

This package is intentionally separate from `app/`: it measures CodeSage rather than
serving it, and it may change as experiments change. It reads the same retrieval
engine and the `retrieval_logs` table the API writes.
"""
