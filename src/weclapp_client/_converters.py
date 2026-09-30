"""
Conversion between the weclapp representation of dates (milliseconds since the Unix epoch) and Python objects.

The arithmetic uses ``timedelta`` instead of ``datetime.fromtimestamp``: birth dates before 1970 have negative
timestamps, which ``fromtimestamp`` cannot handle on Windows.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from pydantic import BeforeValidator, PlainSerializer

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_ONE_MILLISECOND = timedelta(milliseconds=1)
_HALF_DAY = timedelta(hours=12)


def ms_to_datetime(milliseconds: int) -> datetime:
    """Converts a weclapp timestamp to a timezone-aware ``datetime`` in UTC."""
    return _EPOCH + timedelta(milliseconds=milliseconds)


def datetime_to_ms(value: datetime) -> int:
    """Converts a timezone-aware ``datetime`` to a weclapp timestamp."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("naive datetimes are ambiguous, please pass a timezone-aware datetime")
    return (value - _EPOCH) // _ONE_MILLISECOND


def ms_to_date(milliseconds: int) -> date:
    """
    Converts the timestamp of a date-only field (e.g. ``birthDate``) to a ``date``.

    The timestamp is rounded to the nearest midnight (UTC). This yields the intended date no matter whether weclapp
    stored midnight UTC or midnight in a local timezone such as Europe/Berlin (i.e. 22:00 or 23:00 UTC of the day
    before).
    """
    return (ms_to_datetime(milliseconds) + _HALF_DAY).date()


def date_to_ms(value: date) -> int:
    """Converts a ``date`` to the timestamp of midnight UTC of that day."""
    return datetime_to_ms(datetime(value.year, value.month, value.day, tzinfo=UTC))


def _parse_date(value: object) -> object:
    if isinstance(value, int) and not isinstance(value, bool):
        return ms_to_date(value)
    return value


def _parse_datetime(value: object) -> object:
    if isinstance(value, int) and not isinstance(value, bool):
        return ms_to_datetime(value)
    return value


WeclappDate = Annotated[
    date,
    BeforeValidator(_parse_date),
    PlainSerializer(date_to_ms, return_type=int, when_used="json"),
]
"""a date-only field; weclapp sends and expects milliseconds since the epoch"""

WeclappDateTime = Annotated[
    datetime,
    BeforeValidator(_parse_datetime),
    PlainSerializer(datetime_to_ms, return_type=int, when_used="json"),
]
"""a timestamp field; weclapp sends and expects milliseconds since the epoch"""
