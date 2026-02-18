from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.security import AuditLog, UserSecurityProfile
from app.models.user import ApprovalStatus, User


def cleanup_stale_unverified_pending_users(db: Session) -> int:
    cutoff = datetime.utcnow() - timedelta(hours=settings.cleanup_unverified_pending_after_hours)
    stale_user_ids = db.scalars(
        select(User.id)
        .outerjoin(UserSecurityProfile, UserSecurityProfile.user_id == User.id)
        .where(
            User.created_at < cutoff,
            User.approval_status == ApprovalStatus.PENDING,
            (UserSecurityProfile.id.is_(None)) | (UserSecurityProfile.is_email_verified.is_(False)),
        )
    ).all()

    if not stale_user_ids:
        return 0

    db.execute(delete(User).where(User.id.in_(stale_user_ids)))
    db.add(
        AuditLog(
            event_type="users.cleanup.deleted_stale_pending",
            actor_user_id=None,
            target_user_id=None,
            details=f'{{"count": {len(stale_user_ids)}}}',
        )
    )
    db.commit()
    return len(stale_user_ids)
