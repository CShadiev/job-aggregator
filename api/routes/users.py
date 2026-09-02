from fastapi import APIRouter, HTTPException, status

from api.deps import AppAuth0Client
from logger_provider import LoggerProvider
from models.users import LoginRequest, LoginResponse, RefreshTokenRequest

router = APIRouter(prefix="/users", tags=["users"])
log = LoggerProvider.get_logger()


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, auth0_client: AppAuth0Client) -> LoginResponse:
    """
    Authenticate user with username and password.
    Returns access token, ID token, and refresh token.
    """
    user_log = log.bind(username=request.username)
    try:
        user_log.info("Login attempt")

        # Authenticate with Auth0
        token_data = auth0_client.authenticate(username=request.username, password=request.password)

        user_log.info("Login successful")

        return LoginResponse.model_validate(token_data)

    except ValueError as e:
        # Authentication failed (invalid credentials)
        user_log.warning(f"Authentication failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        ) from e
    except Exception as e:
        # Other errors (network issues, Auth0 unavailable, etc.)
        user_log.error(f"Unexpected error during authentication: {str(e)}")
        raise


@router.post("/refresh", response_model=LoginResponse)
async def refresh_token(
    request: RefreshTokenRequest, auth0_client: AppAuth0Client
) -> LoginResponse:
    """
    Refresh an access token using a refresh token.
    """
    try:
        if not request.refresh_token:
            log.warning("Token refresh attempted without refresh token")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Refresh token is required"
            )

        log.info("Refreshing access token")

        # Refresh the token with Auth0
        token_data = auth0_client.refresh_access_token(request.refresh_token)

        log.info("Access token refreshed successfully")

        return LoginResponse.model_validate(
            {
                **token_data,
                "refresh_token": request.refresh_token,  # Return same refresh token
            }
        )

    except Exception as e:
        log.error(f"Error refreshing token: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Failed to refresh token. Please login again.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e
