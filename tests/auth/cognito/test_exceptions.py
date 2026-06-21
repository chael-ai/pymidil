"""
Tests for midil.auth.cognito.exceptions
"""

import pytest

from pymidil.auth.exceptions import (
    BaseAuthError,
    AuthenticationError,
    AuthorizationError,
)
from pymidil.auth.cognito.exceptions import (
    CognitoAuthenticationError,
    CognitoAuthorizationError,
)


class TestCognitoAuthenticationError:
    """Tests for CognitoAuthenticationError."""

    def test_inheritance(self):
        """Test that CognitoAuthenticationError inherits from AuthenticationError."""
        assert issubclass(CognitoAuthenticationError, AuthenticationError)
        assert issubclass(CognitoAuthenticationError, BaseAuthError)
        assert issubclass(CognitoAuthenticationError, Exception)

    def test_instantiation_without_message(self) -> None:
        """Test instantiating CognitoAuthenticationError without message."""
        error = CognitoAuthenticationError()
        assert isinstance(error, CognitoAuthenticationError)
        assert isinstance(error, AuthenticationError)

    def test_instantiation_with_message(self) -> None:
        """Test instantiating CognitoAuthenticationError with message."""
        message = "Token validation failed"
        error = CognitoAuthenticationError(message)

        assert str(error) == message
        assert isinstance(error, CognitoAuthenticationError)

    def test_can_be_raised(self) -> None:
        """Test that CognitoAuthenticationError can be raised and caught."""
        with pytest.raises(CognitoAuthenticationError):
            raise CognitoAuthenticationError("Test error")

    def test_can_be_caught_as_parent_exception(self) -> None:
        """Test that CognitoAuthenticationError can be caught as parent exceptions."""
        # Can be caught as AuthenticationError
        with pytest.raises(AuthenticationError):
            raise CognitoAuthenticationError("Test error")

        # Can be caught as BaseAuthError
        with pytest.raises(BaseAuthError):
            raise CognitoAuthenticationError("Test error")

        # Can be caught as generic Exception
        with pytest.raises(Exception):
            raise CognitoAuthenticationError("Test error")

    def test_with_complex_message(self) -> None:
        """Test CognitoAuthenticationError with complex error message."""
        error_details = {
            "error": "invalid_client",
            "error_description": "Invalid client credentials",
        }
        message = f"Authentication failed: {error_details}"

        error = CognitoAuthenticationError(message)
        assert str(error) == message

    def test_exception_chaining(self) -> None:
        """Test exception chaining with CognitoAuthenticationError."""
        original_error = ValueError("Original error")

        try:
            raise original_error
        except ValueError as e:
            try:
                raise CognitoAuthenticationError("Cognito error") from e
            except CognitoAuthenticationError as chained_error:
                assert chained_error.__cause__ == original_error


class TestCognitoAuthorizationError:
    """Tests for CognitoAuthorizationError."""

    def test_inheritance(self) -> None:
        """Test that CognitoAuthorizationError inherits from AuthorizationError."""
        assert issubclass(CognitoAuthorizationError, AuthorizationError)
        assert issubclass(CognitoAuthorizationError, BaseAuthError)
        assert issubclass(CognitoAuthorizationError, Exception)

    def test_instantiation_without_message(self) -> None:
        """Test instantiating CognitoAuthorizationError without message."""
        error = CognitoAuthorizationError()
        assert isinstance(error, CognitoAuthorizationError)
        assert isinstance(error, AuthorizationError)

    def test_instantiation_with_message(self) -> None:
        """Test instantiating CognitoAuthorizationError with message."""
        message = "Token verification failed"
        error = CognitoAuthorizationError(message)

        assert str(error) == message
        assert isinstance(error, CognitoAuthorizationError)

    def test_can_be_raised(self) -> None:
        """Test that CognitoAuthorizationError can be raised and caught."""
        with pytest.raises(CognitoAuthorizationError):
            raise CognitoAuthorizationError("Test error")

    def test_can_be_caught_as_parent_exception(self) -> None:
        """Test that CognitoAuthorizationError can be caught as parent exceptions."""
        # Can be caught as AuthorizationError
        with pytest.raises(AuthorizationError):
            raise CognitoAuthorizationError("Test error")

        # Can be caught as BaseAuthError
        with pytest.raises(BaseAuthError):
            raise CognitoAuthorizationError("Test error")

        # Can be caught as generic Exception
        with pytest.raises(Exception):
            raise CognitoAuthorizationError("Test error")

    def test_with_jwt_error_message(self) -> None:
        """Test CognitoAuthorizationError with JWT-specific error message."""
        message = "JWT verification failed: Token is expired"
        error = CognitoAuthorizationError(message)

        assert str(error) == message
        assert "JWT verification failed" in str(error)

    def test_exception_chaining_with_jwt_error(self) -> None:
        """Test exception chaining with JWT library errors."""
        from jwt import InvalidTokenError

        original_error = InvalidTokenError("Invalid signature")

        try:
            raise original_error
        except InvalidTokenError as e:
            try:
                raise CognitoAuthorizationError("Token validation failed") from e
            except CognitoAuthorizationError as chained_error:
                assert chained_error.__cause__ == original_error
                assert isinstance(chained_error.__cause__, InvalidTokenError)


class TestExceptionHierarchy:
    """Tests for the overall exception hierarchy."""

    def test_both_exceptions_share_common_base(self) -> None:
        """Test that both Cognito exceptions share common base classes."""
        auth_error = CognitoAuthenticationError("auth error")
        authz_error = CognitoAuthorizationError("authz error")

        # Both should be BaseAuthError
        assert isinstance(auth_error, BaseAuthError)
        assert isinstance(authz_error, BaseAuthError)

        # Both should be Exception
        assert isinstance(auth_error, Exception)
        assert isinstance(authz_error, Exception)

    def test_exceptions_are_distinct(self) -> None:
        """Test that the two exception types are distinct."""
        assert CognitoAuthenticationError != CognitoAuthorizationError
        assert not issubclass(CognitoAuthenticationError, CognitoAuthorizationError)
        assert not issubclass(CognitoAuthorizationError, CognitoAuthenticationError)

    def test_catching_specific_vs_generic_exceptions(self) -> None:
        """Test catching specific vs generic exceptions."""

        # Test catching specific exception
        with pytest.raises(CognitoAuthenticationError):
            raise CognitoAuthenticationError("specific error")

        # Test catching as generic BaseAuthError
        try:
            raise CognitoAuthenticationError("generic error")
        except BaseAuthError as e:
            assert isinstance(e, CognitoAuthenticationError)

    def test_error_messages_preserved_through_hierarchy(self) -> None:
        """Test that error messages are preserved when caught as parent types."""
        message = "Detailed error message with context"

        try:
            raise CognitoAuthenticationError(message)
        except BaseAuthError as e:
            assert str(e) == message

        try:
            raise CognitoAuthorizationError(message)
        except BaseAuthError as e:
            assert str(e) == message
