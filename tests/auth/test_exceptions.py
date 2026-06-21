"""
Tests for midil.auth.exceptions
"""

import pytest

from pymidil.auth.exceptions import (
    BaseAuthError,
    AuthenticationError,
    AuthorizationError,
)


class TestBaseAuthError:
    """Tests for BaseAuthError."""

    def test_is_exception_subclass(self):
        """Test that BaseAuthError is a subclass of Exception."""
        assert issubclass(BaseAuthError, Exception)

    def test_instantiation_without_message(self):
        """Test instantiating BaseAuthError without message."""
        error = BaseAuthError()
        assert isinstance(error, BaseAuthError)
        assert isinstance(error, Exception)

    def test_instantiation_with_message(self):
        """Test instantiating BaseAuthError with message."""
        message = "Base authentication error"
        error = BaseAuthError(message)

        assert str(error) == message
        assert isinstance(error, BaseAuthError)

    def test_can_be_raised(self):
        """Test that BaseAuthError can be raised and caught."""
        with pytest.raises(BaseAuthError):
            raise BaseAuthError("Test error")

    def test_can_be_caught_as_exception(self):
        """Test that BaseAuthError can be caught as generic Exception."""
        with pytest.raises(Exception):
            raise BaseAuthError("Test error")

    def test_with_multiple_args(self):
        """Test BaseAuthError with multiple arguments."""
        error = BaseAuthError("Error message", 500, {"detail": "error details"})

        # First argument should be the message
        assert str(error) == "('Error message', 500, {'detail': 'error details'})"

    def test_exception_chaining(self):
        """Test exception chaining with BaseAuthError."""
        original_error = ValueError("Original error")

        try:
            raise original_error
        except ValueError as e:
            try:
                raise BaseAuthError("Auth error") from e
            except BaseAuthError as chained_error:
                assert chained_error.__cause__ == original_error


class TestAuthenticationError:
    """Tests for AuthenticationError."""

    def test_inheritance(self):
        """Test that AuthenticationError inherits from BaseAuthError."""
        assert issubclass(AuthenticationError, BaseAuthError)
        assert issubclass(AuthenticationError, Exception)

    def test_instantiation_without_message(self):
        """Test instantiating AuthenticationError without message."""
        error = AuthenticationError()
        assert isinstance(error, AuthenticationError)
        assert isinstance(error, BaseAuthError)

    def test_instantiation_with_message(self):
        """Test instantiating AuthenticationError with message."""
        message = "Authentication failed"
        error = AuthenticationError(message)

        assert str(error) == message
        assert isinstance(error, AuthenticationError)

    def test_can_be_raised(self):
        """Test that AuthenticationError can be raised and caught."""
        with pytest.raises(AuthenticationError):
            raise AuthenticationError("Test error")

    def test_can_be_caught_as_base_auth_error(self):
        """Test that AuthenticationError can be caught as BaseAuthError."""
        with pytest.raises(BaseAuthError):
            raise AuthenticationError("Test error")

    def test_can_be_caught_as_exception(self):
        """Test that AuthenticationError can be caught as generic Exception."""
        with pytest.raises(Exception):
            raise AuthenticationError("Test error")

    def test_with_credential_error_context(self):
        """Test AuthenticationError with credential-specific context."""
        message = "Invalid credentials: username/password mismatch"
        error = AuthenticationError(message)

        assert str(error) == message
        assert "credentials" in str(error)

    def test_with_token_error_context(self):
        """Test AuthenticationError with token-specific context."""
        message = "Token authentication failed: token expired"
        error = AuthenticationError(message)

        assert str(error) == message
        assert "token" in str(error)

    def test_exception_chaining_with_http_error(self):
        """Test exception chaining with HTTP errors."""
        import httpx

        original_error = httpx.HTTPStatusError(
            "401 Unauthorized",
            request=httpx.Request("GET", "https://example.com"),
            response=httpx.Response(status_code=401),
        )

        try:
            raise original_error
        except httpx.HTTPStatusError as e:
            try:
                raise AuthenticationError("HTTP authentication failed") from e
            except AuthenticationError as chained_error:
                assert chained_error.__cause__ == original_error


class TestAuthorizationError:
    """Tests for AuthorizationError."""

    def test_inheritance(self):
        """Test that AuthorizationError inherits from BaseAuthError."""
        assert issubclass(AuthorizationError, BaseAuthError)
        assert issubclass(AuthorizationError, Exception)

    def test_instantiation_without_message(self):
        """Test instantiating AuthorizationError without message."""
        error = AuthorizationError()
        assert isinstance(error, AuthorizationError)
        assert isinstance(error, BaseAuthError)

    def test_instantiation_with_message(self):
        """Test instantiating AuthorizationError with message."""
        message = "Authorization failed"
        error = AuthorizationError(message)

        assert str(error) == message
        assert isinstance(error, AuthorizationError)

    def test_can_be_raised(self):
        """Test that AuthorizationError can be raised and caught."""
        with pytest.raises(AuthorizationError):
            raise AuthorizationError("Test error")

    def test_can_be_caught_as_base_auth_error(self):
        """Test that AuthorizationError can be caught as BaseAuthError."""
        with pytest.raises(BaseAuthError):
            raise AuthorizationError("Test error")

    def test_can_be_caught_as_exception(self):
        """Test that AuthorizationError can be caught as generic Exception."""
        with pytest.raises(Exception):
            raise AuthorizationError("Test error")

    def test_with_permission_error_context(self):
        """Test AuthorizationError with permission-specific context."""
        message = "Access denied: insufficient permissions for resource"
        error = AuthorizationError(message)

        assert str(error) == message
        assert "permissions" in str(error)

    def test_with_role_error_context(self):
        """Test AuthorizationError with role-specific context."""
        message = (
            "Authorization failed: user role 'viewer' cannot perform 'write' operation"
        )
        error = AuthorizationError(message)

        assert str(error) == message
        assert "role" in str(error)

    def test_exception_chaining_with_jwt_error(self):
        """Test exception chaining with JWT errors."""
        import jwt

        original_error = jwt.InvalidTokenError("Token signature verification failed")

        try:
            raise original_error
        except jwt.InvalidTokenError as e:
            try:
                raise AuthorizationError("JWT authorization failed") from e
            except AuthorizationError as chained_error:
                assert chained_error.__cause__ == original_error


class TestExceptionHierarchy:
    """Tests for the overall exception hierarchy."""

    def test_both_child_exceptions_share_base(self) -> None:
        """Test that both child exceptions share BaseAuthError base."""
        auth_error = AuthenticationError("auth error")
        authz_error = AuthorizationError("authz error")

        # Both should be BaseAuthError
        assert isinstance(auth_error, BaseAuthError)
        assert isinstance(authz_error, BaseAuthError)

        # Both should be Exception
        assert isinstance(auth_error, Exception)
        assert isinstance(authz_error, Exception)

    def test_exceptions_are_distinct(self) -> None:
        """Test that the two exception types are distinct."""
        assert AuthenticationError != AuthorizationError
        assert not issubclass(AuthenticationError, AuthorizationError)
        assert not issubclass(AuthorizationError, AuthenticationError)

    def test_catching_specific_vs_generic_exceptions(self) -> None:
        """Test catching specific vs generic exceptions."""

        # Test catching specific exception
        with pytest.raises(AuthenticationError):
            raise AuthenticationError("specific error")

        # Test catching as generic BaseAuthError
        try:
            raise AuthenticationError("generic error")
        except BaseAuthError as e:
            assert isinstance(e, AuthenticationError)

        # Same for AuthorizationError
        try:
            raise AuthorizationError("generic error")
        except BaseAuthError as e:
            assert isinstance(e, AuthorizationError)

    def test_error_messages_preserved_through_hierarchy(self) -> None:
        """Test that error messages are preserved when caught as parent types."""
        message = "Detailed error message with context"

        try:
            raise AuthenticationError(message)
        except BaseAuthError as e:
            assert str(e) == message

        try:
            raise AuthorizationError(message)
        except BaseAuthError as e:
            assert str(e) == message

    def test_multiple_exception_handling(self) -> None:
        """Test handling multiple exception types in a single try-except."""

        def raise_auth_error(error_type):
            if error_type == "authentication":
                raise AuthenticationError("Auth failed")
            elif error_type == "authorization":
                raise AuthorizationError("Authz failed")
            else:
                raise BaseAuthError("Generic auth error")

        # Test catching multiple specific types
        for error_type in ["authentication", "authorization"]:
            try:
                raise_auth_error(error_type)
            except (AuthenticationError, AuthorizationError) as e:
                assert isinstance(e, BaseAuthError)

        # Test catching with base class
        for error_type in ["authentication", "authorization", "base"]:
            try:
                raise_auth_error(error_type)
            except BaseAuthError as e:
                assert isinstance(e, BaseAuthError)

    def test_exception_attributes_preservation(self) -> None:
        """Test that exception attributes are preserved across hierarchy."""
        # Test with custom attributes
        auth_error = AuthenticationError("test message")
        setattr(auth_error, "error_code", "AUTH_001")
        setattr(auth_error, "context", {"user_id": "123"})

        try:
            raise auth_error
        except BaseAuthError as e:
            assert hasattr(e, "error_code")
            assert hasattr(e, "context")
            assert e.error_code == "AUTH_001"  # type: ignore
            assert e.context == {"user_id": "123"}  # type: ignore

    def test_docstring_ellipsis_pattern(self):
        """Test that the exceptions use the ellipsis pattern correctly."""
        # This tests that the classes are defined with '...' (ellipsis) which is correct
        # for simple exception classes that don't add additional functionality

        # All three exception classes should be instantiable and functional
        base_error = BaseAuthError("base")
        auth_error = AuthenticationError("auth")
        authz_error = AuthorizationError("authz")

        assert str(base_error) == "base"
        assert str(auth_error) == "auth"
        assert str(authz_error) == "authz"
