from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.security import AuditLog, UserSecurityProfile
from app.models.user import ApprovalStatus, User


def maybe_activate_user_account(db: Session, user: User, profile: UserSecurityProfile) -> bool:
    if user.approval_status != ApprovalStatus.APPROVED:
        return False
    if settings.email_verification_enabled and not profile.is_email_verified:
        return False

    existing = db.scalar(
        select(AuditLog).where(
            AuditLog.event_type == "users.activated",
            AuditLog.target_user_id == user.id,
        )
    )
    if existing:
        return False

    # Hook for downstream provisioning tasks (billing/workspace/notifications/etc.).
    db.add(
        AuditLog(
            event_type="users.activated",
            actor_user_id=user.id,
            target_user_id=user.id,
            details='{"provisioning":"completed"}',
        )
    )
    return True
