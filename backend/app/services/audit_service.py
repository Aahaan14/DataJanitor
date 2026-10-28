"""
DataJanitor — audit trail writer.

`log()` only adds the row to the session; the caller commits it in the SAME
transaction as the change it describes, so the log can never disagree with
the data. Details must contain ids and counts only — never cell values.
"""

from typing import Optional

from sqlalchemy.orm import Session

from app.database.base import utcnow
from app.models.records import AuditRow


def log(session: Session, event_type: str, entity_type: str, entity_id: Optional[str], *,
        dataset_id: Optional[str] = None, plan_id: Optional[str] = None,
        details: Optional[dict] = None, actor: str = "anonymous") -> None:
    session.add(AuditRow(
        timestamp=utcnow(), event_type=event_type, entity_type=entity_type,
        entity_id=entity_id, dataset_id=dataset_id, plan_id=plan_id,
        actor=actor, details=details or {},
    ))
