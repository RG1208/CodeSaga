"""Insert demo data for local development: `python -m app.db.seed`.

Idempotent: running it twice does not create duplicates. Seeded repositories
are registered but not indexed; start indexing from the UI or the API.
"""

import logging

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import get_session_factory
from app.models import Project, Repository, RepositorySourceType, User
from app.repositories import ProjectRepository, RepositoryRepository, UserRepository

logger = logging.getLogger("app.seed")

DEMO_EMAIL = "demo@codesage.local"
DEMO_PROJECT = "CodeSage Demo"
# (owner, name, branch) — small public repositories that clone in seconds.
DEMO_REPOSITORIES = [
    ("pallets", "markupsafe", "main"),
    ("pallets", "itsdangerous", "main"),
]


def seed() -> None:
    with get_session_factory()() as session:
        users, projects, repositories = (
            UserRepository(session),
            ProjectRepository(session),
            RepositoryRepository(session),
        )

        user = users.get_by_email(DEMO_EMAIL) or users.add(
            User(email=DEMO_EMAIL, full_name="Demo User")
        )
        project = projects.get_by_name(DEMO_PROJECT) or projects.add(
            Project(
                name=DEMO_PROJECT,
                description="Sample repositories for exploring the CodeSage UI.",
                owner_id=user.id,
            )
        )
        created = 0
        for owner, name, branch in DEMO_REPOSITORIES:
            url = f"https://github.com/{owner}/{name}"
            if repositories.get_by_project_and_url(project.id, url) is None:
                repositories.add(
                    Repository(
                        project_id=project.id,
                        name=name,
                        owner=owner,
                        url=url,
                        source_type=RepositorySourceType.GITHUB,
                        default_branch=branch,
                        branch=branch,
                    )
                )
                created += 1

        session.commit()
        logger.info("seed complete", extra={"repositories_created": created})


if __name__ == "__main__":
    settings = get_settings()
    configure_logging(settings.log_level, "console")
    seed()
