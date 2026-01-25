"""Authentication Service API."""

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from datetime import timedelta

import sys
sys.path.append("../../core")

from framework.auth.models import UserCreate, UserLogin, UserResponse, Token
from framework.auth.jwt_handler import JWTHandler
from framework.auth.audit_logger import AuditLogger


app = FastAPI(
    title="Authentication Service",
    description="Enterprise authentication and authorization service",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure properly in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize services
jwt_handler = JWTHandler(secret_key="your-secret-key-change-in-production")
audit_logger = AuditLogger()

# In-memory user storage (replace with database)
users_db = {}


@app.post("/api/v1/auth/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(user_data: UserCreate):
    """Register a new user."""
    # Check if user exists
    if user_data.email in users_db:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Create user
    from framework.auth.models import User
    password_hash = jwt_handler.hash_password(user_data.password)

    user = User(
        email=user_data.email,
        name=user_data.name,
    )

    # Store user (in production, save to database)
    users_db[user_data.email] = {
        "user": user,
        "password_hash": password_hash
    }

    # Log registration
    await audit_logger.log(
        action="user.register",
        user_id=user.id,
        resource_type="user",
        resource_id=user.id
    )

    return user


@app.post("/api/v1/auth/login", response_model=Token)
async def login(login_data: UserLogin):
    """Authenticate user and return tokens."""
    # Get user
    user_data = users_db.get(login_data.email)
    if not user_data:
        await audit_logger.log(
            action="login.failed",
            resource_type="auth",
            metadata={"email": login_data.email}
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    user = user_data["user"]
    password_hash = user_data["password_hash"]

    # Verify password
    if not jwt_handler.verify_password(login_data.password, password_hash):
        await audit_logger.log_login(user.id, success=False)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    # Generate tokens
    access_token = jwt_handler.create_access_token(
        user_id=str(user.id),
        email=user.email,
        scopes=["read", "write"]
    )
    refresh_token = jwt_handler.create_refresh_token(str(user.id))

    # Log successful login
    await audit_logger.log_login(user.id, success=True)

    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=1800  # 30 minutes
    )


@app.post("/api/v1/auth/refresh", response_model=Token)
async def refresh_token(refresh_token: str):
    """Refresh access token using refresh token."""
    try:
        payload = jwt_handler.decode_token(refresh_token)
        user_id = payload.sub

        # Get user
        user = next((u["user"] for u in users_db.values() if str(u["user"].id) == user_id), None)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token"
            )

        # Generate new access token
        access_token = jwt_handler.create_access_token(
            user_id=str(user.id),
            email=user.email,
            scopes=["read", "write"]
        )
        new_refresh_token = jwt_handler.create_refresh_token(str(user.id))

        return Token(
            access_token=access_token,
            refresh_token=new_refresh_token,
            token_type="bearer",
            expires_in=1800
        )

    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )


@app.get("/api/v1/auth/me", response_model=UserResponse)
async def get_current_user(current_user: dict = Depends(lambda: {"id": "test"})):
    """Get current user profile."""
    # In production, extract from JWT token
    return current_user


@app.post("/api/v1/auth/logout")
async def logout():
    """Logout user (invalidate tokens)."""
    # In production, add token to blacklist
    return {"message": "Successfully logged out"}


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "auth-service"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
