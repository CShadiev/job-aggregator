"""Auth0 authentication service and JWT token validation."""

import json
from urllib.request import urlopen

from auth0.authentication import GetToken, RevokeToken, Users
from auth0.authentication.exceptions import Auth0Error
from authlib.jose import JsonWebKey
from authlib.jose.errors import ExpiredTokenError, InvalidTokenError, JoseError
from authlib.oauth2.rfc7523 import JWTBearerTokenValidator
from expiringdict import ExpiringDict

from config import Config
from logger_provider import LoggerProvider

log = LoggerProvider.get_logger()
log = log.bind(service="auth_service")


class Auth0JWTBearerTokenValidator(JWTBearerTokenValidator):
    """
    JWT Bearer Token Validator for Auth0 tokens.
    Validates JWT tokens using Auth0's JWKS and enforces claims validation.
    """

    def __init__(self, domain: str, audience: str):
        """
        Initialize the validator with Auth0 domain and audience.

        Args:
            domain: Auth0 domain (e.g., 'your-tenant.auth0.com')
            audience: Auth0 API identifier/audience
        """
        self.issuer = f"https://{domain}/"
        self.audience = audience

        # Fetch JWKS from Auth0
        jsonurl = urlopen(f"{self.issuer}.well-known/jwks.json")
        public_key = JsonWebKey.import_key_set(json.loads(jsonurl.read()))

        # Initialize parent class with the public key
        super().__init__(public_key)

        # Configure claims validation
        self.claims_options = {
            "exp": {"essential": True},
            "aud": {"essential": True, "value": audience},
            "iss": {"essential": True, "value": self.issuer},
        }


class Auth0ClientWrapper:
    """
    Wrapper for Auth0 authentication service using the official Auth0 Python SDK.
    Handles user authentication, token validation, and session management.
    """

    def __init__(self, config: Config):
        """Initialize Auth0 client wrapper with credentials and SDK endpoints.

        Args:
            config: Application configuration containing Auth0 settings.
        """
        self.config = config
        self.domain = config.AUTH0_DOMAIN
        self.client_id = config.AUTH0_CLIENT_ID
        self.client_secret = config.AUTH0_CLIENT_SECRET
        self.audience = config.AUTH0_AUDIENCE
        self.issuer = f"https://{self.domain}/"
        self.cache: dict = ExpiringDict(max_len=100, max_age_seconds=60)

        # Initialize Auth0 SDK clients
        self.get_token = GetToken(
            domain=self.domain, client_id=self.client_id, client_secret=self.client_secret
        )
        self.users = Users(domain=self.domain)
        self.revoke = RevokeToken(
            domain=self.domain, client_id=self.client_id, client_secret=self.client_secret
        )

        # Initialize JWT validator
        self.jwt_validator = Auth0JWTBearerTokenValidator(
            domain=self.domain, audience=self.audience
        )

    def authenticate(self, username: str, password: str) -> dict:
        """
        Authenticate user with username and password using Auth0 Resource
         Owner Password flow.

        Args:
            username: User's username or email
            password: User's password

        Returns:
            Dictionary containing access_token, id_token, token_type, and expires_in

        Raises:
            ValueError: If authentication fails
            Auth0Error: If the request to Auth0 fails
        """
        log.info(f"Authenticating user: {username}")

        try:
            # Use Auth0 SDK's login method for Resource Owner Password Grant
            token_data = self.get_token.login(
                username=username,
                password=password,
                scope="openid profile email offline_access username",
                audience=self.audience,
                grant_type="password",
            )

            log.info(f"Successfully authenticated user: {username}")

            return {
                "access_token": token_data["access_token"],
                "id_token": token_data.get("id_token"),
                "token_type": token_data.get("token_type"),
                "expires_in": token_data.get("expires_in"),
                "refresh_token": token_data.get("refresh_token"),
            }

        except Auth0Error as e:
            log.error(f"Authentication failed for user {username}: {e}")
            # Extract error message from Auth0Error
            error_msg = str(e.message) if hasattr(e, "message") else str(e)
            raise ValueError(error_msg) from e
        except Exception as e:
            log.error(f"Unexpected error during authentication: {e}")
            raise ValueError(f"Authentication failed: {str(e)}") from e

    def verify_token(self, token: str) -> dict:
        """
        Verify and decode an Auth0 access token using authlib's JWT validator.

        Args:
            token: JWT access token to verify

        Returns:
            Decoded token payload

        Raises:
            JoseError: If token verification fails
            ExpiredTokenError: If token has expired
            InvalidTokenError: If token is invalid
        """
        try:
            # Authenticate and validate the token using authlib
            token_data = self.jwt_validator.authenticate_token(token)
            if not token_data:
                log.error("Token validation failed: No token data returned")
                raise InvalidTokenError("Invalid token")
            log.info(f"Successfully verified token for user: {token_data.get('sub')}")
            return token_data

        except ExpiredTokenError:
            log.error("Token has expired")
            raise
        except InvalidTokenError as e:
            log.error(f"Invalid token: {e}")
            raise
        except JoseError as e:
            log.error(f"Token verification failed: {e}")
            raise
        except Exception as e:
            log.error(f"Unexpected error during token verification: {e}")
            raise

    def revoke_token(self, token: str) -> bool:
        """
        Revoke a refresh token using Auth0 SDK.
        Note: Access tokens cannot be revoked in Auth0, they must expire naturally.

        Args:
            token: Refresh token to revoke

        Returns:
            True if successful

        Raises:
            Auth0Error: If the request fails
        """
        log.info("Revoking refresh token")

        try:
            # Use Auth0 SDK's revoke method
            self.revoke.revoke_refresh_token(token=token)
            log.info("Successfully revoked token")
            return True

        except Auth0Error as e:
            log.error(f"Failed to revoke token: {e}")
            raise
        except Exception as e:
            log.error(f"Unexpected error during token revocation: {e}")
            raise

    def get_user_info(self, access_token: str) -> dict:
        """
        Get user information from Auth0 using an access token via Auth0 SDK.

        Args:
            access_token: Valid Auth0 access token

        Returns:
            User profile information

        Raises:
            Auth0Error: If the request fails
        """
        log.info("Fetching user info from Auth0")
        user_info = self.cache.get(access_token, None)
        if user_info:
            log.info("User info fetched from cache")
            return user_info

        try:
            # Use Auth0 SDK's userinfo method
            user_info = self.users.userinfo(access_token=access_token)
            log.info(f"Successfully fetched user info for: {user_info.get('sub')}")
            self.cache[access_token] = user_info
            return user_info

        except Auth0Error as e:
            log.error(f"Failed to fetch user info: {e}")
            raise
        except Exception as e:
            log.error(f"Unexpected error fetching user info: {e}")
            raise

    def refresh_access_token(self, refresh_token: str) -> dict:
        """
        Refresh an access token using a refresh token via Auth0 SDK.

        Args:
            refresh_token: Valid refresh token

        Returns:
            Dictionary containing new access_token and other token data

        Raises:
            Auth0Error: If the request fails
        """
        log.info("Refreshing access token")

        try:
            # Use Auth0 SDK's refresh_token method
            token_data = self.get_token.refresh_token(refresh_token=refresh_token)

            log.info("Successfully refreshed access token")

            return {
                "access_token": token_data["access_token"],
                "id_token": token_data.get("id_token"),
                "token_type": token_data.get("token_type", "Bearer"),
                "expires_in": token_data.get("expires_in", 86400),
            }

        except Auth0Error as e:
            log.error(f"Failed to refresh token: {e}")
            raise
        except Exception as e:
            log.error(f"Unexpected error during token refresh: {e}")
            raise
