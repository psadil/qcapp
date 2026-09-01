"""Application-level exceptions (Django Styleguide error architecture)."""


class ApplicationError(Exception):
    def __init__(self, message: str, extra: dict | None = None):
        super().__init__(message)
        self.message = message
        self.extra = extra or {}


class NotFound(ApplicationError):
    """A referenced object does not exist."""


class PushRejected(ApplicationError):
    """A pushed unit contradicts what the server holds or requires (409)."""


class PushTooLarge(ApplicationError):
    """A pushed payload exceeds a configured ceiling (413)."""
