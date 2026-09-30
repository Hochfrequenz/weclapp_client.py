from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from weclapp_client.models import (
    CustomAttribute,
    CustomAttributeDefinition,
    CustomAttributeType,
    Employee,
    EmployeeCreate,
    EmployeeUpdate,
    EmploymentStatus,
    User,
    UserCreate,
    UserStatus,
    UserUpdate,
)

from .helpers import load_fixture


def test_user_is_parsed_and_unknown_properties_are_ignored() -> None:
    user = User.model_validate(load_fixture("user"))

    assert user.id == "4711"
    assert user.version == "3"
    assert user.first_name == "Erika"
    assert user.last_name == "Musterfrau"
    assert user.status is UserStatus.NOT_ACTIVE
    assert user.can_edit_dashboard is False
    assert user.created_date == datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
    assert not hasattr(user, "phone_number")


def test_user_custom_attribute_lookup() -> None:
    user = User.model_validate(load_fixture("user"))

    personnel_number = user.custom_attribute("9001")
    assert personnel_number is not None
    assert personnel_number.string_value == "00042"
    other = user.custom_attribute("9002")
    assert other is not None
    assert other.string_value is None
    assert user.custom_attribute("does-not-exist") is None


def test_unknown_enum_values_are_kept_as_strings() -> None:
    data = load_fixture("user") | {"status": "SOMETHING_NEW"}
    user = User.model_validate(data)
    assert user.status == "SOMETHING_NEW"
    assert not isinstance(user.status, UserStatus)


def test_read_models_require_id_and_version() -> None:
    with pytest.raises(ValidationError):
        User.model_validate({"firstName": "Erika"})


def test_minimal_user_has_defaults() -> None:
    user = User.model_validate({"id": "1", "version": "0"})
    assert user.custom_attributes == []
    assert user.status is None
    assert user.created_date is None


def test_employee_is_parsed() -> None:
    employee = Employee.model_validate(load_fixture("employee"))

    assert employee.id == "5100"
    assert employee.employee_number == "1001"
    assert employee.user_id == "4711"
    assert employee.birth_date == date(1985, 4, 12)
    assert employee.employment_status is EmploymentStatus.ACTIVE


def test_employee_birth_date_before_1970() -> None:
    employee = Employee.model_validate({"id": "1", "version": "0", "birthDate": -631152000000})
    assert employee.birth_date == date(1950, 1, 1)


def test_custom_attribute_definition_is_parsed() -> None:
    definition = CustomAttributeDefinition.model_validate(load_fixture("custom_attribute_definition"))
    assert definition.attribute_key == "personalnummer"
    assert definition.attribute_type is CustomAttributeType.STRING
    assert definition.entities == ["user"]


def test_python_dump_keeps_python_types() -> None:
    employee = Employee.model_validate(load_fixture("employee"))
    assert employee.model_dump()["birthDate"] == date(1985, 4, 12)
    assert employee.model_dump(mode="json")["birthDate"] == 482112000000


# ----------------------------------------------------------------------------------------------------------------------
# write models


def test_user_create_payload() -> None:
    data = UserCreate(
        email="erika.musterfrau@example.com",
        status=UserStatus.NOT_ACTIVE,
        first_name="Erika",
        custom_attributes=[CustomAttribute.of_string("9001", "00042")],
    )
    assert data.to_payload() == {
        "email": "erika.musterfrau@example.com",
        "status": "NOT_ACTIVE",
        "canEditDashboard": False,
        "firstName": "Erika",
        "customAttributes": [{"attributeDefinitionId": "9001", "stringValue": "00042"}],
    }


def test_user_create_requires_email_and_status() -> None:
    with pytest.raises(ValidationError) as error_info:
        UserCreate.model_validate({"firstName": "Erika"})
    missing = {error["loc"][0] for error in error_info.value.errors()}
    assert missing == {"email", "status"}


@pytest.mark.parametrize(
    "data",
    [
        {"email": "", "status": "NOT_ACTIVE"},
        {"email": "a@example.com", "status": "NOT_ACTIVE", "first_name": "x" * 51},
        {"email": "a@example.com", "status": "NOT_ACTIVE", "last_name": "x" * 51},
        {"email": "a@example.com", "status": "UNKNOWN"},
        {"email": "a@example.com", "status": "NOT_ACTIVE", "username": "not writable"},
    ],
)
def test_user_create_rejects_invalid_data(data: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        UserCreate.model_validate(data)


def test_names_with_50_characters_are_accepted() -> None:
    data = UserCreate(email="a@example.com", status=UserStatus.ACTIVE, first_name="x" * 50, last_name="y" * 50)
    assert data.first_name == "x" * 50


def test_user_update_sends_only_fields_set_explicitly() -> None:
    assert UserUpdate(first_name="Erika").to_payload() == {"firstName": "Erika"}
    assert UserUpdate(last_name=None).to_payload() == {"lastName": None}
    assert UserUpdate().to_payload() == {}


def test_user_update_with_custom_attribute() -> None:
    payload = UserUpdate(custom_attributes=[CustomAttribute.of_string("9001", None)]).to_payload()
    assert payload == {"customAttributes": [{"attributeDefinitionId": "9001", "stringValue": None}]}


def test_write_models_reject_read_only_and_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        EmployeeUpdate.model_validate({"employeeNumber": "1001"})
    with pytest.raises(ValidationError):
        UserUpdate.model_validate({"version": "3"})


def test_write_models_accept_api_property_names() -> None:
    assert UserUpdate.model_validate({"firstName": "Erika"}).first_name == "Erika"


def test_employee_create_payload() -> None:
    assert EmployeeCreate(user_id="4711", birth_date=date(1985, 4, 12)).to_payload() == {
        "userId": "4711",
        "birthDate": 482112000000,
    }
    assert EmployeeCreate(user_id="4711").to_payload() == {"userId": "4711"}


def test_employee_create_requires_a_user() -> None:
    with pytest.raises(ValidationError):
        EmployeeCreate(user_id="")


def test_employee_update_payload() -> None:
    assert EmployeeUpdate(birth_date=date(1950, 1, 1)).to_payload() == {"birthDate": -631152000000}
    assert EmployeeUpdate(birth_date=None).to_payload() == {"birthDate": None}


def test_birth_date_rejects_booleans() -> None:
    with pytest.raises(ValidationError):
        EmployeeUpdate.model_validate({"birthDate": True})
