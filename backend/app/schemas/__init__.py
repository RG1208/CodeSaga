"""Pydantic schemas: the request/response contract of the HTTP API.

Schemas are deliberately separate from ORM models so the database layout can
change without breaking API clients (and vice versa).
"""
