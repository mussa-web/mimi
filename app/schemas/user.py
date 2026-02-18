from datetime import datetime

from pydantic import BaseModel

from app.models.user import ApprovalStatus, UserRole


class UserOut(BaseModel):
    id: int
    email: str
    username: str
    shop_id: int
    is_global_access: bool = False
    role: UserRole
    approval_status: ApprovalStatus
    is_email_verified: bool = False
    mfa_enabled: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}
