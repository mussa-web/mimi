import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.core.config import settings
from app.core.security import (
    create_access_token,
    generate_session_id,
    generate_token_secret,
    hash_password,
    hash_token,
    verify_password,
)
from app.db.database import get_db
from app.models.inventory import Shop
from app.models.security import AuditLog, OneTimeToken, OneTimeTokenType, RefreshSession, UserSecurityProfile
from app.models.user import ApprovalStatus, User, UserRole
from app.schemas.auth import (
    CleanupResponse,
    EmailVerificationRequest,
    GenericMessageResponse,
    LoginRequest,
    LogoutRequest,
    MfaEnableRequest,
    MfaSetupResponse,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    RefreshRequest,
    SessionOut,
    SignUpRequest,
    SignUpResponse,
    TokenPairResponse,
    VerifyEmailRequest,
)
from app.schemas.user import UserOut
from app.services.cleanup import cleanup_stale_unverified_pending_users
from app.services.email_service import (
    EmailDeliveryError,
    build_password_reset_message,
    build_verification_message,
    send_email,
)
from app.services.provisioning import maybe_activate_user_account

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _has_global_shop_access(user: User) -> bool:
    return user.role == UserRole.SYSTEM_OWNER or user.is_global_access


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._attempts: dict[str, list[datetime]] = defaultdict(list)

    def check(self, key: str) -> bool:
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(seconds=settings.login_rate_limit_window_seconds)
        self._attempts[key] = [dt for dt in self._attempts[key] if dt >= window_start]
        return len(self._attempts[key]) >= settings.login_rate_limit_max_attempts

    def hit(self, key: str) -> None:
        self._attempts[key].append(datetime.now(timezone.utc))

    def clear(self, key: str) -> None:
        self._attempts.pop(key, None)


login_rate_limiter = SlidingWindowLimiter()


def get_client_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def log_audit(
    db: Session,
    event_type: str,
    actor_user_id: int | None,
    target_user_id: int | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    details: dict | None = None,
) -> None:
    audit = AuditLog(
        event_type=event_type,
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        ip_address=ip_address,
        user_agent=user_agent,
        details=json.dumps(details or {}),
    )
    db.add(audit)


def get_or_create_security_profile(
    db: Session,
    user_id: int,
    default_verified: bool = False,
) -> UserSecurityProfile:
    profile = db.scalar(select(UserSecurityProfile).where(UserSecurityProfile.user_id == user_id))
    if profile:
        return profile
    profile = UserSecurityProfile(user_id=user_id, is_email_verified=default_verified)
    db.add(profile)
    db.flush()
    return profile


def issue_refresh_session(
    db: Session,
    user_id: int,
    ip_address: str | None,
    user_agent: str | None,
) -> tuple[str, RefreshSession]:
    session_id = generate_session_id()
    session_secret = generate_token_secret()
    raw_token = f"{session_id}.{session_secret}"
    refresh_session = RefreshSession(
        id=session_id,
        user_id=user_id,
        token_hash=hash_token(raw_token),
        ip_address=ip_address,
        user_agent=user_agent,
        expires_at=datetime.utcnow() + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(refresh_session)
    return raw_token, refresh_session


def create_one_time_token(
    db: Session,
    user_id: int,
    token_type: OneTimeTokenType,
    expires_in_minutes: int,
) -> str:
    raw_token = generate_token_secret()
    db.add(
        OneTimeToken(
            id=generate_session_id(),
            user_id=user_id,
            token_type=token_type,
            token_hash=hash_token(raw_token),
            expires_at=datetime.utcnow() + timedelta(minutes=expires_in_minutes),
        )
    )
    return raw_token


def parse_refresh_token(raw_token: str) -> tuple[str, str]:
    parts = raw_token.split(".", 1)
    if len(parts) != 2:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    return parts[0], parts[1]


def authenticate_user(
    db: Session,
    identity: str,
    password: str,
    otp: str | None,
    request: Request,
) -> User:
    ip = get_client_ip(request) or "unknown"
    rate_key = f"{ip}:{identity.lower()}"
    if login_rate_limiter.check(rate_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts, try again later",
        )

    user = db.scalar(
        select(User).where(
            or_(
                func.lower(User.email) == identity.lower(),
                func.lower(User.username) == identity.lower(),
            )
        )
    )

    if not user:
        login_rate_limiter.hit(rate_key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    profile = get_or_create_security_profile(
        db,
        user.id,
        default_verified=user.approval_status == ApprovalStatus.APPROVED,
    )
    now_utc = datetime.now(timezone.utc)
    if profile.locked_until and profile.locked_until.replace(tzinfo=timezone.utc) > now_utc:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Account is temporarily locked due to failed login attempts",
        )

    if not verify_password(password, user.password_hash):
        login_rate_limiter.hit(rate_key)
        profile.failed_login_attempts += 1
        if profile.failed_login_attempts >= settings.login_rate_limit_max_attempts:
            profile.locked_until = datetime.utcnow() + timedelta(minutes=settings.account_lockout_minutes)
            profile.failed_login_attempts = 0
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user.approval_status != ApprovalStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account pending system owner approval",
        )
    if settings.email_verification_enabled and not profile.is_email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email verification required before login",
        )
    if profile.mfa_enabled:
        if not otp or not profile.mfa_secret or not pyotp.TOTP(profile.mfa_secret).verify(otp, valid_window=1):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Valid MFA code is required",
            )

    profile.failed_login_attempts = 0
    profile.locked_until = None
    profile.last_login_at = datetime.utcnow()
    login_rate_limiter.clear(rate_key)
    db.commit()
    db.refresh(user)
    return user


def user_out_with_security(db: Session, user: User) -> UserOut:
    profile = get_or_create_security_profile(
        db,
        user.id,
        default_verified=user.approval_status == ApprovalStatus.APPROVED,
    )
    return UserOut(
        id=user.id,
        email=user.email,
        username=user.username,
        shop_id=user.shop_id,
        is_global_access=user.is_global_access,
        role=user.role,
        approval_status=user.approval_status,
        is_email_verified=profile.is_email_verified,
        mfa_enabled=profile.mfa_enabled,
        created_at=user.created_at,
    )


@router.post("/signup", response_model=SignUpResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: SignUpRequest, request: Request, db: Session = Depends(get_db)):
    requested_shop_code = payload.shop_id.strip().upper()
    assigned_shop = db.scalar(select(Shop).where(func.upper(Shop.code) == requested_shop_code))
    if not assigned_shop:
        shop_name = (payload.shop_name or payload.shop_id).strip()
        if len(shop_name) < 2:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Shop name must be at least 2 chars")
        assigned_shop = Shop(
            code=requested_shop_code,
            name=shop_name,
            location=(payload.shop_location.strip() if payload.shop_location else None),
        )
        db.add(assigned_shop)
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Shop code already exists") from exc

    if not assigned_shop:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assigned shop not found")

    existing = db.scalar(
        select(User).where(
            or_(
                func.lower(User.email) == payload.email.lower(),
                func.lower(User.username) == payload.username.lower(),
            )
        )
    )
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email or username already exists")

    if payload.role == UserRole.BUSINESS_OWNER:
        existing_owner = db.scalar(
            select(User).where(
                User.role == UserRole.BUSINESS_OWNER,
                User.shop_id == assigned_shop.id,
                User.approval_status.in_([ApprovalStatus.PENDING, ApprovalStatus.APPROVED]),
            )
        )
        if existing_owner:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This shop already has a business owner",
            )

    if payload.role == UserRole.SYSTEM_OWNER:
        owner_count = db.scalar(select(func.count(User.id)).where(User.role == UserRole.SYSTEM_OWNER)) or 0
        if owner_count > 0:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="System owner registration is closed",
            )
        approval_status = ApprovalStatus.APPROVED
        is_email_verified = True
    else:
        approval_status = ApprovalStatus.PENDING
        is_email_verified = not settings.email_verification_enabled

    user = User(
        email=payload.email.lower(),
        username=payload.username,
        password_hash=hash_password(payload.password),
        shop_id=assigned_shop.id,
        role=payload.role,
        approval_status=approval_status,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email or username already exists") from exc

    profile = UserSecurityProfile(user_id=user.id, is_email_verified=is_email_verified)
    db.add(profile)
    log_audit(
        db=db,
        event_type="auth.signup",
        actor_user_id=user.id,
        target_user_id=user.id,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        details={"role": user.role.value, "approval_status": user.approval_status.value},
    )
    verification_email_sent: bool | None = None
    if settings.email_verification_enabled and not is_email_verified:
        verification_token = create_one_time_token(
            db=db,
            user_id=user.id,
            token_type=OneTimeTokenType.EMAIL_VERIFICATION,
            expires_in_minutes=settings.email_verification_token_expire_minutes,
        )
        try:
            subject, text_body, html_body = build_verification_message(verification_token)
            send_email(user.email, subject, text_body, html_body)
            verification_email_sent = True
        except EmailDeliveryError:
            verification_email_sent = False

    maybe_activate_user_account(db, user, profile)
    db.commit()

    message = (
        "Signup successful. Account approved."
        if approval_status == ApprovalStatus.APPROVED
        else (
            "Signup successful. Awaiting system owner approval and email verification."
            if settings.email_verification_enabled
            else "Signup successful. Awaiting system owner approval."
        )
    )
    return SignUpResponse(
        user_id=user.id,
        email=user.email,
        username=user.username,
        role=user.role,
        approval_status=user.approval_status,
        email_verification_required=not is_email_verified,
        verification_email_sent=verification_email_sent,
        message=message,
    )


def _create_token_pair(db: Session, user: User, request: Request) -> TokenPairResponse:
    access_token = create_access_token(subject=str(user.id), role=user.role.value)
    refresh_token, _ = issue_refresh_session(
        db=db,
        user_id=user.id,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    return TokenPairResponse.from_tokens(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/login", response_model=TokenPairResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    user = authenticate_user(
        db=db,
        identity=payload.identity,
        password=payload.password,
        otp=payload.otp,
        request=request,
    )
    log_audit(
        db=db,
        event_type="auth.login.success",
        actor_user_id=user.id,
        target_user_id=user.id,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return _create_token_pair(db=db, user=user, request=request)


@router.post("/token", response_model=TokenPairResponse)
def login_for_access_token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = authenticate_user(
        db=db,
        identity=form_data.username,
        password=form_data.password,
        otp=None,
        request=request,
    )
    log_audit(
        db=db,
        event_type="auth.token.success",
        actor_user_id=user.id,
        target_user_id=user.id,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return _create_token_pair(db=db, user=user, request=request)


@router.post("/refresh", response_model=TokenPairResponse)
def refresh_tokens(payload: RefreshRequest, request: Request, db: Session = Depends(get_db)):
    session_id, _ = parse_refresh_token(payload.refresh_token)
    current_session = db.get(RefreshSession, session_id)
    if not current_session or current_session.token_hash != hash_token(payload.refresh_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    if current_session.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token already revoked")
    if current_session.expires_at < datetime.utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")

    user = db.get(User, current_session.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    profile = get_or_create_security_profile(
        db,
        user.id,
        default_verified=user.approval_status == ApprovalStatus.APPROVED,
    )
    if user.approval_status != ApprovalStatus.APPROVED or (
        settings.email_verification_enabled and not profile.is_email_verified
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not eligible for refresh",
        )

    new_refresh_token, new_session = issue_refresh_session(
        db=db,
        user_id=user.id,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    current_session.revoked_at = datetime.utcnow()
    current_session.replaced_by_session_id = new_session.id
    access_token = create_access_token(subject=str(user.id), role=user.role.value)
    log_audit(
        db=db,
        event_type="auth.refresh",
        actor_user_id=user.id,
        target_user_id=user.id,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        details={"old_session_id": current_session.id, "new_session_id": new_session.id},
    )
    db.commit()

    return TokenPairResponse.from_tokens(
        access_token=access_token,
        refresh_token=new_refresh_token,
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/logout", response_model=GenericMessageResponse)
def logout(
    payload: LogoutRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session_id, _ = parse_refresh_token(payload.refresh_token)
    refresh_session = db.get(RefreshSession, session_id)
    if (
        refresh_session
        and refresh_session.user_id == current_user.id
        and refresh_session.token_hash == hash_token(payload.refresh_token)
        and refresh_session.revoked_at is None
    ):
        refresh_session.revoked_at = datetime.utcnow()
        log_audit(
            db=db,
            event_type="auth.logout",
            actor_user_id=current_user.id,
            target_user_id=current_user.id,
            ip_address=get_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            details={"session_id": refresh_session.id},
        )
        db.commit()
    return GenericMessageResponse(message="Logged out successfully")


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return user_out_with_security(db, current_user)


@router.get("/pending-users", response_model=list[UserOut])
def list_pending_users(
    admin_user: User = Depends(require_permission("users:view_pending")),
    db: Session = Depends(get_db),
):
    shop_scope = [] if _has_global_shop_access(admin_user) else [User.shop_id == admin_user.shop_id]
    users = db.scalars(
        select(User)
        .where(
            User.approval_status == ApprovalStatus.PENDING,
            User.role.in_([UserRole.BUSINESS_OWNER, UserRole.EMPLOYEE]),
            *shop_scope,
        )
        .order_by(User.created_at.asc())
    ).all()
    return [user_out_with_security(db, user) for user in users]


@router.post("/users/{user_id}/approve", response_model=UserOut)
def approve_user(
    user_id: int,
    request: Request,
    admin_user: User = Depends(require_permission("users:approve")),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.role == UserRole.SYSTEM_OWNER:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="System owner does not require approval")
    if not _has_global_shop_access(admin_user) and user.shop_id != admin_user.shop_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot approve users outside your shop")

    user.approval_status = ApprovalStatus.APPROVED
    profile = get_or_create_security_profile(
        db,
        user.id,
        default_verified=not settings.email_verification_enabled,
    )
    maybe_activate_user_account(db, user, profile)
    log_audit(
        db=db,
        event_type="users.approved",
        actor_user_id=admin_user.id,
        target_user_id=user.id,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    db.refresh(user)
    return user_out_with_security(db, user)


@router.post("/users/{user_id}/reject", response_model=UserOut)
def reject_user(
    user_id: int,
    request: Request,
    admin_user: User = Depends(require_permission("users:reject")),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.role == UserRole.SYSTEM_OWNER:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="System owner does not require approval")
    if not _has_global_shop_access(admin_user) and user.shop_id != admin_user.shop_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot reject users outside your shop")

    user.approval_status = ApprovalStatus.REJECTED
    log_audit(
        db=db,
        event_type="users.rejected",
        actor_user_id=admin_user.id,
        target_user_id=user.id,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    db.refresh(user)
    return user_out_with_security(db, user)


@router.post("/email-verification/request", response_model=GenericMessageResponse)
def request_email_verification(payload: EmailVerificationRequest, db: Session = Depends(get_db)):
    if not settings.email_verification_enabled:
        return GenericMessageResponse(message="Email verification is temporarily disabled")

    user = db.scalar(select(User).where(func.lower(User.email) == payload.email.lower()))
    if not user:
        return GenericMessageResponse(message="If this account exists, a verification email has been sent")

    profile = get_or_create_security_profile(
        db,
        user.id,
        default_verified=user.approval_status == ApprovalStatus.APPROVED,
    )
    if profile.is_email_verified:
        return GenericMessageResponse(message="Email is already verified")

    verification_token = create_one_time_token(
        db=db,
        user_id=user.id,
        token_type=OneTimeTokenType.EMAIL_VERIFICATION,
        expires_in_minutes=settings.email_verification_token_expire_minutes,
    )
    email_sent = True
    try:
        subject, text_body, html_body = build_verification_message(verification_token)
        send_email(user.email, subject, text_body, html_body)
    except EmailDeliveryError:
        email_sent = False
    db.commit()

    return GenericMessageResponse(
        message="Verification email prepared.",
        debug_token=verification_token if settings.expose_debug_tokens else None,
        email_sent=email_sent,
    )


@router.post("/email-verification/verify", response_model=GenericMessageResponse)
def verify_email(payload: VerifyEmailRequest, db: Session = Depends(get_db)):
    token_hash = hash_token(payload.token)
    token = db.scalar(
        select(OneTimeToken).where(
            OneTimeToken.token_hash == token_hash,
            OneTimeToken.token_type == OneTimeTokenType.EMAIL_VERIFICATION,
        )
    )
    if not token or token.used_at is not None or token.expires_at < datetime.utcnow():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")

    profile = get_or_create_security_profile(db, token.user_id, default_verified=False)
    profile.is_email_verified = True
    user = db.get(User, token.user_id)
    if user:
        maybe_activate_user_account(db, user, profile)
    token.used_at = datetime.utcnow()
    db.commit()
    return GenericMessageResponse(message="Email verified successfully")


@router.post("/password-reset/request", response_model=GenericMessageResponse)
def request_password_reset(payload: PasswordResetRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(func.lower(User.email) == payload.email.lower()))
    if not user:
        return GenericMessageResponse(message="If this account exists, a reset token has been sent")

    reset_token = create_one_time_token(
        db=db,
        user_id=user.id,
        token_type=OneTimeTokenType.PASSWORD_RESET,
        expires_in_minutes=settings.password_reset_token_expire_minutes,
    )
    email_sent = True
    try:
        subject, text_body, html_body = build_password_reset_message(reset_token)
        send_email(user.email, subject, text_body, html_body)
    except EmailDeliveryError:
        email_sent = False
    db.commit()

    return GenericMessageResponse(
        message="Password reset email prepared.",
        debug_token=reset_token if settings.expose_debug_tokens else None,
        email_sent=email_sent,
    )


@router.post("/password-reset/confirm", response_model=GenericMessageResponse)
def confirm_password_reset(payload: PasswordResetConfirmRequest, db: Session = Depends(get_db)):
    token_hash = hash_token(payload.token)
    token = db.scalar(
        select(OneTimeToken).where(
            OneTimeToken.token_hash == token_hash,
            OneTimeToken.token_type == OneTimeTokenType.PASSWORD_RESET,
        )
    )
    if not token or token.used_at is not None or token.expires_at < datetime.utcnow():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")

    user = db.get(User, token.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.password_hash = hash_password(payload.new_password)
    token.used_at = datetime.utcnow()
    profile = get_or_create_security_profile(
        db,
        user.id,
        default_verified=user.approval_status == ApprovalStatus.APPROVED,
    )
    profile.password_changed_at = datetime.utcnow()
    sessions = db.scalars(
        select(RefreshSession).where(
            RefreshSession.user_id == user.id,
            RefreshSession.revoked_at.is_(None),
        )
    ).all()
    for session in sessions:
        session.revoked_at = datetime.utcnow()

    db.commit()
    return GenericMessageResponse(message="Password reset successful")


@router.post("/mfa/setup", response_model=MfaSetupResponse)
def setup_mfa(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = get_or_create_security_profile(
        db,
        current_user.id,
        default_verified=current_user.approval_status == ApprovalStatus.APPROVED,
    )
    temp_secret = pyotp.random_base32()
    profile.mfa_temp_secret = temp_secret
    db.commit()

    provisioning_uri = pyotp.TOTP(temp_secret).provisioning_uri(
        name=current_user.email,
        issuer_name=settings.issuer,
    )
    return MfaSetupResponse(
        message="Scan the secret with your authenticator app, then call /auth/mfa/enable",
        secret=temp_secret if settings.expose_debug_tokens else None,
        provisioning_uri=provisioning_uri,
    )


@router.post("/mfa/enable", response_model=GenericMessageResponse)
def enable_mfa(
    payload: MfaEnableRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = get_or_create_security_profile(
        db,
        current_user.id,
        default_verified=current_user.approval_status == ApprovalStatus.APPROVED,
    )
    if not profile.mfa_temp_secret:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA setup is required first")

    if not pyotp.TOTP(profile.mfa_temp_secret).verify(payload.otp, valid_window=1):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OTP")

    profile.mfa_secret = profile.mfa_temp_secret
    profile.mfa_temp_secret = None
    profile.mfa_enabled = True
    db.commit()
    return GenericMessageResponse(message="MFA enabled")


@router.post("/mfa/disable", response_model=GenericMessageResponse)
def disable_mfa(
    payload: MfaEnableRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = get_or_create_security_profile(
        db,
        current_user.id,
        default_verified=current_user.approval_status == ApprovalStatus.APPROVED,
    )
    if not profile.mfa_enabled or not profile.mfa_secret:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA is not enabled")
    if not pyotp.TOTP(profile.mfa_secret).verify(payload.otp, valid_window=1):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OTP")

    profile.mfa_enabled = False
    profile.mfa_secret = None
    profile.mfa_temp_secret = None
    db.commit()
    return GenericMessageResponse(message="MFA disabled")


@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sessions = db.scalars(
        select(RefreshSession)
        .where(RefreshSession.user_id == current_user.id)
        .order_by(RefreshSession.created_at.desc())
    ).all()
    return list(sessions)


@router.post("/sessions/{session_id}/revoke", response_model=GenericMessageResponse)
def revoke_session(
    session_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = db.get(RefreshSession, session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    can_revoke_any = current_user.role == UserRole.SYSTEM_OWNER
    if session.user_id != current_user.id and not can_revoke_any:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to revoke this session")

    if session.revoked_at is None:
        session.revoked_at = datetime.utcnow()
        log_audit(
            db=db,
            event_type="sessions.revoked",
            actor_user_id=current_user.id,
            target_user_id=session.user_id,
            ip_address=get_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            details={"session_id": session.id},
        )
        db.commit()
    return GenericMessageResponse(message="Session revoked")


@router.post("/maintenance/cleanup-stale-users", response_model=CleanupResponse)
def cleanup_stale_users(
    request: Request,
    admin_user: User = Depends(require_permission("users:approve")),
    db: Session = Depends(get_db),
):
    deleted_count = cleanup_stale_unverified_pending_users(db)
    log_audit(
        db=db,
        event_type="users.cleanup.triggered",
        actor_user_id=admin_user.id,
        target_user_id=None,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        details={"deleted_users": deleted_count},
    )
    db.commit()
    return CleanupResponse(
        deleted_users=deleted_count,
        cutoff_hours=settings.cleanup_unverified_pending_after_hours,
        message="Cleanup completed",
    )
