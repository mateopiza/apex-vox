"""
What may be shown to users (app/errors.py)
------------------------------------------
Exception text from ffmpeg, HTTP clients and providers can contain server paths, internal URLs or
provider details. It belongs in the logs. Code that writes a message for the user raises
`UserFacingError`; everything else reaches the client as a generic message.
"""

from __future__ import annotations

GENERIC_ERROR = (
    "No pudimos completar la operación. Intenta de nuevo en unos minutos. / "
    "We could not complete this. Please try again in a few minutes."
)


class UserFacingError(Exception):
    """An error whose message was written for the user and is safe to show."""


def public_error(exc: BaseException) -> str:
    """The text a client may see for this exception."""
    # PermissionError carries the quota and plan messages, written by this app.
    if isinstance(exc, (UserFacingError, PermissionError)) and str(exc):
        return str(exc)
    return GENERIC_ERROR


def detail_of(exc: KeyError) -> str:
    """A KeyError's message. `str(KeyError("x"))` would show it wrapped in quotes."""
    return str(exc.args[0]) if exc.args else GENERIC_ERROR
