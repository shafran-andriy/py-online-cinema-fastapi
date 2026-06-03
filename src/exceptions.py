class BaseEmailError(Exception):
    """Base exception for email sending failures in notifications."""
    pass


class AppError(Exception):
    """Generic application-level exception placeholder."""
    pass


class TokenExpiredError(Exception):
    """Raised when a JWT token has expired."""
    pass


class InvalidTokenError(Exception):
    """Raised when a JWT token is invalid or cannot be decoded."""
    pass


class BaseSecurityError(AppError):
    """Base exception for security-related errors."""
    pass
