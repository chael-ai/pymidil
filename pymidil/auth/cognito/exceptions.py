from pymidil.auth.exceptions import AuthenticationError, AuthorizationError


class CognitoAuthenticationError(AuthenticationError):
    """Exception raised when authentication with Cognito fails."""

    ...


class CognitoAuthorizationError(AuthorizationError):
    """Exception raised when authorization with Cognito fails."""

    ...
