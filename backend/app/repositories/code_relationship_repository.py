import uuid
from collections.abc import Sequence

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.analysis.results import Confidence, RelationshipType
from app.models.code import CodeRelationship


class CodeRelationshipRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def search(
        self,
        repository_id: uuid.UUID,
        *,
        relationship_type: RelationshipType | None = None,
        confidence: Confidence | None = None,
        file_id: uuid.UUID | None = None,
        symbol_id: uuid.UUID | None = None,
        direction: str = "both",
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[Sequence[CodeRelationship], int]:
        statement: Select = select(CodeRelationship).where(
            CodeRelationship.repository_id == repository_id
        )
        if relationship_type is not None:
            statement = statement.where(CodeRelationship.relationship_type == relationship_type)
        if confidence is not None:
            statement = statement.where(CodeRelationship.confidence == confidence)
        for column_pair, value in (
            ((CodeRelationship.source_file_id, CodeRelationship.target_file_id), file_id),
            ((CodeRelationship.source_symbol_id, CodeRelationship.target_symbol_id), symbol_id),
        ):
            if value is None:
                continue
            outgoing, incoming = column_pair[0] == value, column_pair[1] == value
            statement = statement.where(
                outgoing
                if direction == "outgoing"
                else incoming
                if direction == "incoming"
                else or_(outgoing, incoming)
            )
        total = self.session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        rows = self.session.scalars(
            statement.order_by(
                CodeRelationship.relationship_type,
                CodeRelationship.weight.desc(),
                CodeRelationship.id,
            )
            .offset(offset)
            .limit(limit)
        ).all()
        return rows, total

    def file_edges(self, file_id: uuid.UUID) -> Sequence[CodeRelationship]:
        """File-level import edges into and out of one file."""
        return self.session.scalars(
            select(CodeRelationship).where(
                CodeRelationship.relationship_type == RelationshipType.IMPORTS,
                or_(
                    CodeRelationship.source_file_id == file_id,
                    CodeRelationship.target_file_id == file_id,
                ),
            )
        ).all()
