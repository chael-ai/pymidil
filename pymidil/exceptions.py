__all__ = [
    "MidilError",
    # Auth
    "BaseAuthError",
    "AuthenticationError",
    "AuthorizationError",
    # Event
    "BaseEventError",
    "ConsumerError",
    "ConsumerCrashError",
    "ConsumerNotImplementedError",
    "ConsumerStartError",
    "ConsumerStopError",
    "RetryableEventError",
    "NonRetryableEventError",
    "ProducerError",
    "ProducerNotImplementedError",
    "TransportNotImplementedError",
    # Settings
    "SettingsError",
    "AuthSettingsError",
    "EventSettingsError",
    "ApiSettingsError",
    # Cursor
    "CursorError",
    "InvalidCursorError",
    "ExpiredCursorError",
]


class MidilError(Exception):
    """Base exception for all pymidil errors."""

    ...


# ── Auth ──────────────────────────────────────────────────────────────────────


class BaseAuthError(MidilError):
    """Base exception for all authentication and authorization errors."""

    ...


class AuthenticationError(BaseAuthError):
    """Exception raised when authentication fails."""

    ...


class AuthorizationError(BaseAuthError):
    """Exception raised when authorization fails."""

    ...


# ── Event ─────────────────────────────────────────────────────────────────────


class BaseEventError(MidilError):
    """Base class for all event errors."""

    pass


class ConsumerError(BaseEventError):
    """Base class for consumer errors."""

    pass


class ConsumerCrashError(ConsumerError):
    """Exception raised when a consumer crashes."""

    pass


class ConsumerNotImplementedError(ConsumerError):
    """Exception raised when a consumer type is not implemented."""

    def __init__(self, type: str):
        self.type = type
        ConsumerError.__init__(self, f"Consumer type '{type}' is not implemented.")


class ConsumerStartError(ConsumerError):
    """Exception raised when a consumer fails to start."""

    pass


class ConsumerStopError(ConsumerError):
    """Exception raised when a consumer fails to stop."""

    pass


class RetryableEventError(BaseEventError):
    """Raised by a subscriber to signal the message should be requeued and retried."""

    pass


class NonRetryableEventError(BaseEventError):
    """Raised by a subscriber to signal the message should be discarded without retry."""

    pass


class ProducerError(BaseEventError):
    """Base class for producer errors."""

    pass


class ProducerNotImplementedError(ProducerError):
    """Exception raised when a producer type is not implemented."""

    def __init__(self, type: str):
        self.type = type
        ProducerError.__init__(self, f"Producer type '{type}' is not implemented.")


class TransportNotImplementedError(BaseEventError):
    """Exception raised when a transport type is not implemented."""

    def __init__(self, type: str):
        self.type = type
        BaseEventError.__init__(self, f"Transport type '{type}' is not implemented.")


# ── Settings ──────────────────────────────────────────────────────────────────


class SettingsError(MidilError):
    """Base exception for settings-related errors."""

    ...


class AuthSettingsError(SettingsError):
    """Exception for authentication settings errors."""

    ...


class EventSettingsError(SettingsError):
    """Exception for event settings errors."""

    ...


class ApiSettingsError(SettingsError):
    """Exception for API settings errors."""

    ...


# ── Cursor / Pagination ───────────────────────────────────────────────────────


class CursorError(MidilError):
    """Base cursor exception."""


class InvalidCursorError(CursorError):
    """Raised when cursor is malformed."""


class ExpiredCursorError(CursorError):
    """Raised when cursor is expired."""
