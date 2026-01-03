from datetime import datetime
import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException, status

from auth import (
    create_access_token,
    get_current_user_id,
    get_password_hash,
    verify_password,
)
from database import cosmos_db
from models import LoginRequest, Token, UserCreate, UserResponse

# Text reduction: renamed variables/loggers while keeping authentication behavior identical
auth_logger = logging.getLogger("auth_router")

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=Token, status_code=status.HTTP_200_OK)
async def register_account(account_payload: UserCreate):
    """
    Register a new user account
    """
    try:
        auth_logger.info(f"Registration attempt for email: {account_payload.email}")
        existing_account = cosmos_db.get_user_by_email(account_payload.email)
        if existing_account:
            auth_logger.warning(
                f"Registration failed: Email already exists {account_payload.email}"
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User with this email already exists",
            )

        account_id = str(uuid.uuid4())
        account_doc = {
            "id": account_id,
            "username": account_payload.username,
            "email": account_payload.email,
            "hashed_password": get_password_hash(account_payload.password),
            "created_at": datetime.utcnow().isoformat(),
        }

        persisted_user = cosmos_db.create_user(account_doc)
        auth_logger.info(f"User created successfully: {account_payload.email}")

        access_token = create_access_token(
            data={"sub": account_id, "email": account_payload.email}
        )

        response_body = UserResponse(
            id=persisted_user["id"],
            username=persisted_user["username"],
            email=persisted_user["email"],
            createdAt=persisted_user["created_at"],
        )

        return Token(token=access_token, user=response_body)

    except HTTPException:
        raise
    except ValueError as e:
        auth_logger.error(f"Registration validation error: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        auth_logger.error(f"Registration error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to register user: {str(e)}",
        )


@router.post("/login", response_model=Token, status_code=status.HTTP_200_OK)
async def login_account(credentials_payload: LoginRequest):
    """
    Authenticate user and receive access token
    """
    try:
        auth_logger.info(f"Login attempt for email: {credentials_payload.email}")
        account_record = cosmos_db.get_user_by_email(credentials_payload.email)
        if not account_record:
            auth_logger.warning(
                f"Login failed: User not found for email {credentials_payload.email}"
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

        if not verify_password(
            credentials_payload.password, account_record["hashed_password"]
        ):
            auth_logger.warning(
                f"Login failed: Invalid password for email {credentials_payload.email}"
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

        access_token = create_access_token(
            data={"sub": account_record["id"], "email": account_record["email"]}
        )

        response_body = UserResponse(
            id=account_record["id"],
            username=account_record["username"],
            email=account_record["email"],
            createdAt=account_record["created_at"],
        )

        auth_logger.info(f"Login successful for user: {account_record['email']}")
        return Token(token=access_token, user=response_body)

    except HTTPException:
        raise
    except Exception as e:
        auth_logger.error(f"Login error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to login: {str(e)}",
        )
