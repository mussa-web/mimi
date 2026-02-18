from datetime import datetime

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.user import ApprovalStatus, UserRole


class SignUpRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    email: str = Field(min_length=5, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    username: str = Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_]+$")
    password: str = Field(min_length=10, max_length=128)
    shop_id: str = Field(min_length=1, max_length=100, alias="shopId")
    shop_name: str | None = Field(default=None, min_length=2, max_length=120, alias="shopName")
    shop_location: str | None = Field(default=None, max_length=255, alias="shopLocation")
    role: UserRole = UserRole.EMPLOYEE

    @field_validator("role", mode="before")
    @classmethod
    def normalize_role(cls, value: str | UserRole):
        if isinstance(value, UserRole):
            return value
        if not isinstance(value, str):
            return value
        normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
        if normalized == "bussiness_owner":
            normalized = "business_owner"
        return normalized


class SignUpResponse(BaseModel):
    user_id: int
    email: str
    username: str
    role: UserRole
    approval_status: ApprovalStatus
    email_verification_required: bool
    verification_email_sent: bool | None = None
    message: str


class LoginRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    identity: str = Field(min_length=1, max_length=320, description="Email or username")
    password: str = Field(min_length=1, max_length=128)
    otp: str | None = Field(default=None, min_length=6, max_length=6)

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_identity_fields(cls, data):
        if not isinstance(data, dict):
            return data
        if data.get("identity"):
            return data
        for key in ("email", "username"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                data["identity"] = value
                break
        return data

    @field_validator("identity")
    @classmethod
    def normalize_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("identity must not be empty")
        return normalized

    @field_validator("otp", mode="before")
    @classmethod
    def normalize_optional_otp(cls, value):
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class TokenPairResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    accessToken: str
    refreshToken: str
    expiresIn: int
    token: str

    @classmethod
    def from_tokens(
        cls,
        access_token: str,
        refresh_token: str,
        expires_in: int,
    ) -> "TokenPairResponse":
        return cls(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
            accessToken=access_token,
            refreshToken=refresh_token,
            expiresIn=expires_in,
            token=access_token,
        )


class RefreshRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    refresh_token: str = Field(
        min_length=20,
        max_length=512,
        validation_alias=AliasChoices("refresh_token", "refreshToken"),
    )


class LogoutRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    refresh_token: str = Field(
        min_length=20,
        max_length=512,
        validation_alias=AliasChoices("refresh_token", "refreshToken"),
    )


class GenericMessageResponse(BaseModel):
    message: str
    debug_token: str | None = None
    email_sent: bool | None = None


class EmailVerificationRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=20, max_length=512)


class PasswordResetRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class PasswordResetConfirmRequest(BaseModel):
    token: str = Field(min_length=20, max_length=512)
    new_password: str = Field(min_length=10, max_length=128)


class MfaSetupResponse(BaseModel):
    message: str
    secret: str | None = None
    provisioning_uri: str | None = None


class MfaEnableRequest(BaseModel):
    otp: str = Field(min_length=6, max_length=6)


class SessionOut(BaseModel):
    id: str
    ip_address: str | None
    user_agent: str | None
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None

    model_config = {"from_attributes": True}


class CleanupResponse(BaseModel):
    deleted_users: int
    cutoff_hours: int
    message: str
