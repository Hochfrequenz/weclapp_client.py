from datetime import UTC, date, datetime

import pytest

from weclapp_client import InvalidQueryError
from weclapp_client.models import UserStatus
from weclapp_client.query import Filter, validate_filters


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        (Filter.eq("email", "a@example.com"), ("email-eq", "a@example.com")),
        (Filter.eq("canEditDashboard", True), ("canEditDashboard-eq", "true")),
        (Filter.eq("canEditDashboard", False), ("canEditDashboard-eq", "false")),
        (Filter.ne("userId", 4711), ("userId-ne", "4711")),
        (Filter.lt("birthDate", date(1970, 1, 2)), ("birthDate-lt", "86400000")),
        (Filter.le("lastModifiedDate", datetime(1970, 1, 1, 0, 0, 1, tzinfo=UTC)), ("lastModifiedDate-le", "1000")),
        (Filter.gt("lastModifiedDate", 1700000000000), ("lastModifiedDate-gt", "1700000000000")),
        (Filter.ge("version", "2"), ("version-ge", "2")),
        (Filter.eq("status", UserStatus.NOT_ACTIVE), ("status-eq", "NOT_ACTIVE")),
        (Filter.like("lastName", "Muster%"), ("lastName-like", "Muster%")),
        (Filter.ilike("lastName", "muster%"), ("lastName-ilike", "muster%")),
        (Filter.null("email"), ("email-null", "")),
        (Filter.not_null("email"), ("email-notnull", "")),
        (Filter.in_("id", ["1", "2"]), ("id-in", '["1", "2"]')),
        (Filter.in_("status", [UserStatus.ACTIVE, UserStatus.NOT_ACTIVE]), ("status-in", '["ACTIVE", "NOT_ACTIVE"]')),
        (Filter.not_in("birthDate", [date(1970, 1, 2), 5]), ("birthDate-notin", "[86400000, 5]")),
        (Filter.custom_attribute_eq("9001", "00042"), ("customAttribute9001-eq", "00042")),
    ],
)
def test_filters_become_query_parameters(condition: Filter, expected: tuple[str, str]) -> None:
    assert condition.to_query_param() == expected


def test_empty_property_names_are_rejected() -> None:
    with pytest.raises(InvalidQueryError):
        Filter.eq("", "x")


@pytest.mark.parametrize("definition_id", ["", "90-01", "9001&x=1", "90 01"])
def test_invalid_custom_attribute_ids_are_rejected(definition_id: str) -> None:
    with pytest.raises(InvalidQueryError):
        Filter.custom_attribute_eq(definition_id, "x")


def test_validate_filters_accepts_known_properties_and_custom_attributes() -> None:
    validate_filters([Filter.eq("email", "x"), Filter.custom_attribute_eq("9001", "x")], frozenset({"email"}), "user")


def test_validate_filters_rejects_unknown_properties() -> None:
    with pytest.raises(InvalidQueryError, match="'emial'"):
        validate_filters([Filter.eq("emial", "x")], frozenset({"email"}), "user")
