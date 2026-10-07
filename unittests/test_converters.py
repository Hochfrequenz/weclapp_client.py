from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from weclapp_client._converters import date_to_ms, datetime_to_ms, ms_to_date, ms_to_datetime

ONE_DAY_MS = 86_400_000
BIRTH_DATE_MS = 482_112_000_000  # 1985-04-12T00:00:00Z


def test_epoch() -> None:
    assert ms_to_datetime(0) == datetime(1970, 1, 1, tzinfo=UTC)
    assert datetime_to_ms(datetime(1970, 1, 1, tzinfo=UTC)) == 0


def test_datetime_round_trip_keeps_milliseconds() -> None:
    value = datetime(2026, 9, 30, 10, 15, 30, 123000, tzinfo=UTC)
    assert ms_to_datetime(datetime_to_ms(value)) == value


def test_datetime_in_other_timezone() -> None:
    berlin_summer = timezone(timedelta(hours=2))
    assert datetime_to_ms(datetime(1970, 1, 1, 2, tzinfo=berlin_summer)) == 0


def test_naive_datetimes_are_rejected() -> None:
    with pytest.raises(ValueError, match="naive"):
        datetime_to_ms(datetime(2026, 1, 1))


def test_date_is_written_as_midnight_utc() -> None:
    assert date_to_ms(date(1970, 1, 2)) == ONE_DAY_MS
    assert date_to_ms(date(1985, 4, 12)) == BIRTH_DATE_MS


@pytest.mark.parametrize("value", [date(1969, 12, 31), date(1950, 1, 1), date(1900, 3, 1)])
def test_dates_before_1970_use_negative_timestamps(value: date) -> None:
    milliseconds = date_to_ms(value)
    assert milliseconds < 0
    assert ms_to_date(milliseconds) == value


def test_leap_day_round_trip() -> None:
    assert ms_to_date(date_to_ms(date(2024, 2, 29))) == date(2024, 2, 29)


@pytest.mark.parametrize(
    ("milliseconds", "description"),
    [
        (BIRTH_DATE_MS, "midnight UTC"),
        (BIRTH_DATE_MS - 2 * 3_600_000, "midnight Europe/Berlin, summer time"),
        (BIRTH_DATE_MS - 1 * 3_600_000, "midnight Europe/Berlin, standard time"),
        (BIRTH_DATE_MS + 5 * 3_600_000, "midnight America/New_York"),
        (BIRTH_DATE_MS + 11 * 3_600_000, "late in the day"),
    ],
)
def test_reading_a_date_rounds_to_the_nearest_midnight(milliseconds: int, description: str) -> None:
    assert ms_to_date(milliseconds) == date(1985, 4, 12), description
