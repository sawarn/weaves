"""Runtime errors shared across domain service modules."""


class IdempotencyConflict(ValueError):
    """An idempotency key was reused with a conflicting or failed request."""


class ExecutionCancelled(RuntimeError):
    """A worker observed a cancellation request at a safe boundary."""
