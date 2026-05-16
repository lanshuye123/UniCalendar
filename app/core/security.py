from datetime import datetime, timedelta
from typing import Optional
import hashlib
import base64
import secrets

import bcrypt
from jose import JWTError, jwt
from app.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password. Supports bcrypt and Django PBKDF2 hashes (for migrated users)."""
    # Try bcrypt
    try:
        if hashed_password.startswith("$2"):
            return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())
    except Exception:
        pass

    # Try Django PBKDF2 (format: pbkdf2_sha256$iterations$salt$hash)
    if hashed_password.startswith("pbkdf2_"):
        return _verify_django_pbkdf2(plain_password, hashed_password)

    return False


def _verify_django_pbkdf2(password: str, encoded: str) -> bool:
    """Verify Django PBKDF2 password hash."""
    try:
        algorithm, iterations, salt, hash_val = encoded.split("$", 3)
        iterations = int(iterations)

        if algorithm == "pbkdf2_sha256":
            dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations)
        elif algorithm == "pbkdf2_sha1":
            dk = hashlib.pbkdf2_hmac("sha1", password.encode(), salt.encode(), iterations)
        else:
            return False

        return secrets.compare_digest(base64.b64encode(dk).decode(), hash_val)
    except (ValueError, IndexError):
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "iat": datetime.utcnow(), "iss": settings.OAUTH_ISSUER})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def verify_jwt(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        return None


def generate_code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def generate_verification_code() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(6))
