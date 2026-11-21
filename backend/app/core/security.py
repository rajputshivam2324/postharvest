import hashlib
import hmac
import secrets
from datetime import timedelta
from uuid import uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import Settings
from app.core.time import utcnow
from app.schemas.auth import TokenOut

password_hasher = PasswordHasher()
# Perform equivalent work for nonexistent users. This is not a login credential.
dummy_hash = password_hasher.hash(str(uuid4()))


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    try:
        return password_hasher.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


def issue_token(user_id: str, settings: Settings) -> TokenOut:
    now = utcnow()
    expiry = now + timedelta(minutes=settings.jwt_expiry_minutes)
    token = jwt.encode(
        {
            "sub": user_id,
            "iat": now,
            "nbf": now,
            "exp": expiry,
            "iss": "harvest-monitor",
            "aud": "harvest-api",
            "jti": str(uuid4()),
        },
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    return TokenOut(
        access_token=token, expires_in=settings.jwt_expiry_minutes * 60, expires_at=expiry
    )


def credential_hash(token: str) -> str:
    # Device tokens contain 256 bits of random entropy; SHA-256 is appropriate here.
    return hashlib.sha256(token.encode()).hexdigest()


def verify_credential(token: str, encoded: str) -> bool:
    return hmac.compare_digest(credential_hash(token), encoded)


# No 0, 1, I, L, O or U: a code typed from a screen into a phone must survive misreading.
PAIRING_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"
PAIRING_LENGTH = 8


def new_pairing_code() -> str:
    return "".join(secrets.choice(PAIRING_ALPHABET) for _ in range(PAIRING_LENGTH))


def normalize_pairing_code(raw: str) -> str | None:
    """Accept 'abcd-efgh', 'ABCD EFGH' and similar; return None if it cannot be a code."""
    code = "".join(raw.upper().split()).replace("-", "")
    if len(code) != PAIRING_LENGTH or any(c not in PAIRING_ALPHABET for c in code):
        return None
    return code


def pairing_code_hash(code: str, settings: Settings) -> str:
    # A code is short enough to type, so it is hashed with the server secret: a copy of the
    # database alone cannot be used to recover codes that are still valid.
    key = settings.jwt_secret.get_secret_value().encode()
    return hmac.new(key, b"pairing:" + code.encode(), hashlib.sha256).hexdigest()
