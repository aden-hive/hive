"""Authentication middleware for FastAPI."""

from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .jwt_handler import JWTHandler
from .models import TokenPayload
from .audit_logger import AuditLogger


class AuthMiddleware(BaseHTTPMiddleware):
    """Authentication middleware for FastAPI."""

    def __init__(self, app, jwt_handler: JWTHandler, audit_logger: AuditLogger):
        super().__init__(app)
        self.jwt_handler = jwt_handler
        self.audit_logger = audit_logger

    async def dispatch(self, request: Request, call_next):
        """Process request and add auth context."""
        # Skip auth for certain paths
        if request.url.path in ["/api/v1/auth/login", "/api/v1/auth/register", "/health"]:
            response = await call_next(request)
            return response

        # Extract token from Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing authentication token"
            )

        token = auth_header.split(" ")[1]

        try:
            # Verify token
            payload = self.jwt_handler.verify_token(token)

            # Add user context to request state
            request.state.user_id = payload.sub
            request.state.user_email = payload.email
            request.state.user_scopes = payload.scopes

            # Log API access
            await self.audit_logger.log_api_access(
                user_id=payload.sub,
                method=request.method,
                path=request.url.path,
                status_code=None,  # Will be set after response
                ip_address=request.client.host if request.client else None
            )

        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(e)
            )

        response = await call_next(request)
        return response


# Dependency for protected routes
security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    jwt_handler: JWTHandler = Depends(lambda: JWTHandler(secret_key="secret"))
) -> TokenPayload:
    """Get current user from JWT token."""
    token = credentials.credentials
    try:
        payload = jwt_handler.verify_token(token)
        return payload
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token"
        )


async def require_scope(*scopes: str):
    """Dependency to require specific scopes."""
    def dependency(current_user: TokenPayload = Depends(get_current_user)):
        for scope in scopes:
            if scope not in current_user.scopes:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Missing required scope: {scope}"
                )
        return current_user
    return dependency
