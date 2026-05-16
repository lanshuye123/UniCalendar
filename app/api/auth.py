from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import User, VerificationCode
from app.core.security import hash_password, verify_password, create_access_token, create_refresh_token, generate_verification_code
from app.dependencies import get_current_user
from app.schemas import (
    UserCreate, UserLogin, UserResponse, TokenResponse,
    PasswordResetRequest, PasswordResetVerify, ChangePassword,
    ChangeUsername, EmailVerificationRequest, EmailVerificationVerify,
    MessageResponse,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserResponse)
async def register(data: UserCreate, db: AsyncSession = Depends(get_db)):
    """Register a new user account."""
    # Check existing user
    result = await db.execute(
        select(User).where((User.username == data.username) | (User.email == data.email))
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username or email already taken")

    user = User(
        username=data.username,
        email=data.email,
        hashed_password=hash_password(data.password),
    )
    db.add(user)
    await db.flush()
    return user.dict()


@router.post("/login", response_model=TokenResponse)
async def login(data: UserLogin, db: AsyncSession = Depends(get_db)):
    """Login with username/email and password, receive a JWT access token."""
    # Find user by username or email
    result = await db.execute(
        select(User).where((User.username == data.login) | (User.email == data.login))
    )
    user = result.scalar_one_or_none()
    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")

    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token()
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """Get current authenticated user info."""
    return current_user.dict()


@router.post("/change-password", response_model=MessageResponse)
async def change_password(
    data: ChangePassword,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Change password for authenticated user."""
    if not verify_password(data.old_password, current_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Old password is incorrect")

    current_user.hashed_password = hash_password(data.new_password)
    await db.flush()
    return MessageResponse(message="Password changed successfully")


@router.post("/change-username", response_model=MessageResponse)
async def change_username(
    data: ChangeUsername,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Change username for authenticated user."""
    result = await db.execute(select(User).where(User.username == data.new_username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already taken")

    current_user.username = data.new_username
    await db.flush()
    return MessageResponse(message="Username changed successfully")


@router.post("/password-reset/request", response_model=MessageResponse)
async def request_password_reset(data: PasswordResetRequest, db: AsyncSession = Depends(get_db)):
    """Request a password reset code via email."""
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    if not user:
        # Return same message to avoid user enumeration
        return MessageResponse(message="If the email exists, a reset code has been sent")

    code = generate_verification_code()
    vc = VerificationCode(
        user_id=user.id,
        code=code,
        purpose="password_reset",
        expires_at=VerificationCode.expires_in_minutes(15),
    )
    db.add(vc)
    await db.flush()

    # In production, send email here
    print(f"[Password Reset] Code for {user.email}: {code}")

    return MessageResponse(message="If the email exists, a reset code has been sent")


@router.post("/password-reset/verify", response_model=MessageResponse)
async def verify_reset_code(data: PasswordResetVerify, db: AsyncSession = Depends(get_db)):
    """Verify reset code and change password."""
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid request")

    vc_result = await db.execute(
        select(VerificationCode).where(
            VerificationCode.user_id == user.id,
            VerificationCode.code == data.code,
            VerificationCode.purpose == "password_reset",
            VerificationCode.used == False,
            VerificationCode.expires_at > __import__("datetime").datetime.utcnow(),
        ).order_by(VerificationCode.created_at.desc())
    )
    vc = vc_result.scalar_one_or_none()
    if not vc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired code")

    vc.used = True
    user.hashed_password = hash_password(data.new_password)
    await db.flush()
    return MessageResponse(message="Password reset successfully")


@router.post("/email/verify-request", response_model=MessageResponse)
async def request_email_verification(
    data: EmailVerificationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Request an email verification code."""
    if current_user.is_verified:
        return MessageResponse(message="Email already verified")

    code = generate_verification_code()
    vc = VerificationCode(
        user_id=current_user.id,
        code=code,
        purpose="email",
        expires_at=VerificationCode.expires_in_minutes(15),
    )
    db.add(vc)
    await db.flush()

    print(f"[Email Verify] Code for {current_user.email}: {code}")
    return MessageResponse(message="Verification code sent")


@router.post("/email/verify", response_model=MessageResponse)
async def verify_email(
    data: EmailVerificationVerify,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Verify email with code."""
    vc_result = await db.execute(
        select(VerificationCode).where(
            VerificationCode.user_id == current_user.id,
            VerificationCode.code == data.code,
            VerificationCode.purpose == "email",
            VerificationCode.used == False,
            VerificationCode.expires_at > __import__("datetime").datetime.utcnow(),
        ).order_by(VerificationCode.created_at.desc())
    )
    vc = vc_result.scalar_one_or_none()
    if not vc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired code")

    vc.used = True
    current_user.is_verified = True
    await db.flush()
    return MessageResponse(message="Email verified successfully")
