"""Explicit service-layer errors for Run and Thread lifecycle operations."""


class RunLifecycleError(RuntimeError):
    """Base class for recoverable runtime service failures."""


class ThreadNotFoundError(RunLifecycleError):
    """Raised when a requested thread has no durable checkpoint."""


class ThreadAccessDeniedError(RunLifecycleError):
    """Raised when a user attempts to access another user's thread."""


class RunNotFoundError(RunLifecycleError):
    """Raised when a run identifier does not exist."""


class RunAlreadyActiveError(RunLifecycleError):
    """Raised when a thread already has an active run."""


class InvalidRunTransitionError(RunLifecycleError):
    """Raised when a lifecycle transition is not allowed."""


class RunStateMismatchError(RunLifecycleError):
    """Raised when a run context does not match its durable identity."""


class RunEngineMismatchError(RunLifecycleError):
    """Raised when a caller attempts to continue a run with another engine."""
