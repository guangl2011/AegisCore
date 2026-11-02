"""SCAL error taxonomy.

``MalformedCommandError`` means the task command itself is structurally
invalid (unknown primitive, missing or out-of-domain parameters).
``InfeasibleCommandError`` means the command is well-formed but the given
chassis cannot serve it (geometry, envelope, or missing actuator).
Downstream components branch on these types, never on message strings.
"""


class ScalError(Exception):
    """Base class for SCAL translation failures."""


class MalformedCommandError(ScalError):
    """A task command is structurally invalid or uses an unknown primitive."""


class InfeasibleCommandError(ScalError):
    """A well-formed task command cannot be served by the given chassis."""
