"""Aggregates all v1 endpoint routers. Mounted under `settings.api_v1_prefix`."""

from fastapi import APIRouter

from app.api.v1.endpoints import code, health, projects, repositories, search

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(projects.router)
api_router.include_router(repositories.router)
api_router.include_router(code.router)
api_router.include_router(search.router)
