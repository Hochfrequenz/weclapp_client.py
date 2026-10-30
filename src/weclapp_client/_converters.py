"""
Conversion between the weclapp representation of dates (milliseconds since the Unix epoch) and Python objects.

Date-only fields are written as midnight German time (Europe/Berlin), the way the weclapp user interface stores them.
weclapp requires this for some fields, e.g. the start date of a work schedule profile, and accepts it for all others.

The arithmetic uses ``timedelta`` instead of ``datetime.fromtimestamp``: birth dates before 1970 have negative
timestamps, which ``fromtimestamp`` cannot handle on Windows.
"""

from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import BeforeValidator, PlainSerializer

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_ONE_MILLISECOND = timedelta(milliseconds=1)
_HALF_DAY = timedelta(hours=12)
_DATE_TIMEZONE = ZoneInfo("Europe/Berlin")
"""the timezone in which weclapp stores date-only fields as midnight"""


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
    """Converts a ``date`` to the timestamp of midnight German time, i.e. 22:00 or 23:00 UTC of the day before."""
    return datetime_to_ms(datetime(value.year, value.month, value.day, tzinfo=_DATE_TIMEZONE))


def date_timestamps(value: date) -> tuple[int, int]:
    """
    The timestamps weclapp may hold for a date: midnight German time (the user interface and this client) and the later
    midnight UTC (e.g. version ``0.1.0a1`` of this client). Date filters have to match both.
    """
    return date_to_ms(value), datetime_to_ms(datetime(value.year, value.month, value.day, tzinfo=UTC))


def is_start_of_day(milliseconds: int) -> bool:
    """Whether a timestamp is midnight German time, as weclapp requires it e.g. for the start of a work schedule."""
    return ms_to_datetime(milliseconds).astimezone(_DATE_TIMEZONE).time() == time(0)


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
