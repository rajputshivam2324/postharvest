from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.schemas.common import InputSchema, OutputSchema

Role = Literal["admin", "operator", "vendor"]


class LoginInput(BaseModel):
    # Password whitespace must be preserved.
    model_config = ConfigDict(extra="forbid")
    user_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.@-]+$")
    password: SecretStr = Field(min_length=1, max_length=128)


class UserCreate(LoginInput):
    password: SecretStr = Field(min_length=12, max_length=128)
    role: Role = "operator"


class SignupInput(LoginInput):
    password: SecretStr = Field(min_length=12, max_length=128)
    role: Literal["operator", "vendor"] = "vendor"


class UserUpdate(InputSchema):
    active: bool


class UserOut(OutputSchema):
    id: str
    user_id: str
    role: Role
    active: bool
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    expires_at: datetime


class LoginOut(TokenOut):
    user: UserOut
