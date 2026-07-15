"""Application-level exceptions (Django Styleguide error architecture)."""


class ApplicationError(Exception):
    def __init__(self, message: str, extra: dict | None = None):
        super().__init__(message)
        self.message = message
        self.extra = extra or {}


class NotFound(ApplicationError):
    """A referenced object does not exist."""
