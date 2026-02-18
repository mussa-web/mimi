from datetime import datetime

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_token, hash_token
from app.db.database import get_db
from app.models.security import RefreshSession
from app.models.user import ApprovalStatus, User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)

ROLE_PERMISSIONS: dict[UserRole, set[str]] = {
    UserRole.SYSTEM_OWNER: {
        "users:approve",
        "users:reject",
        "users:view_pending",
        "sessions:revoke_any",
        "inventory:manage",
        "inventory:view",
        "inventory:sell",
    },
    UserRole.BUSINESS_OWNER: {"sessions:revoke_self", "inventory:manage", "inventory:view", "inventory:sell"},
    UserRole.EMPLOYEE: {"sessions:revoke_self", "inventory:view", "inventory:sell"},
}


def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    def _clean_candidate(value: str | None) -> str | None:
        if not value:
            return None
        cleaned = value.strip().strip("\"'").strip()
        if not cleaned:
            return None
        # Normalize accidental duplicated prefixes like: "Bearer Bearer <jwt>"
        while cleaned.lower().startswith("bearer "):
            cleaned = cleaned[7:].strip().strip("\"'").strip()
        return cleaned or None

    raw_token = _clean_candidate(token)
    if not raw_token:
        auth_header = request.headers.get("authorization", "").strip()
        if auth_header:
            parts = auth_header.split(" ", 1)
            if len(parts) == 2 and parts[0].lower() == "bearer":
                raw_token = _clean_candidate(parts[1])
            elif len(parts) == 1:
                # Tolerate clients that send raw token without "Bearer " prefix.
                raw_token = _clean_candidate(parts[0])
            else:
                raw_token = _clean_candidate(auth_header)
        if not raw_token:
            raw_token = _clean_candidate(request.headers.get("x-access-token"))
        if not raw_token:
            raw_token = _clean_candidate(request.cookies.get("access_token"))

    if not raw_token:
        raise credentials_exception

    user_id: int | None = None

    # Primary mode: JWT access token.
    try:
        payload = decode_token(raw_token)
        subject = payload.get("sub")
        token_type = payload.get("type")
        if subject is not None and token_type == "access":
            user_id = int(subject)
    except Exception:
        user_id = None

    # Compatibility mode: some clients mistakenly send refresh token as Bearer token.
    # If it maps to an active, non-revoked, non-expired session, allow auth.
    if user_id is None and raw_token.count(".") == 1:
        refresh_session = db.scalar(
            select(RefreshSession).where(
                RefreshSession.token_hash == hash_token(raw_token),
                RefreshSession.revoked_at.is_(None),
                RefreshSession.expires_at >= datetime.utcnow(),
            )
        )
        if refresh_session:
            user_id = refresh_session.user_id

    if user_id is None:
        raise credentials_exception

    user = db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise credentials_exception
    if user.approval_status != ApprovalStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is not approved",
        )
    return user


def require_system_owner(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.SYSTEM_OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System owner role required",
        )
    return current_user


def require_permission(permission: str):
    def checker(current_user: User = Depends(get_current_user)) -> User:
        permissions = ROLE_PERMISSIONS.get(current_user.role, set())
        if permission not in permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission required: {permission}",
            )
        return current_user

    return checker
