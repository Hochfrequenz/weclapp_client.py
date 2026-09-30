"""
The ``/employee`` resource.
"""

from typing import ClassVar

from weclapp_client.models.employee import Employee, EmployeeCreate, EmployeeUpdate
from weclapp_client.query import Filter
from weclapp_client.resources.base import WriteResource

# property names according to the weclapp OpenAPI specification (v2)
_PROPERTIES = frozenset(
    {
        "birthDate",
        "businessFaxNumber",
        "businessHolidaysId",
        "businessMobileNumber",
        "businessPhoneNumber",
        "childAllowance",
        "createdDate",
        "department",
        "emergencyContact",
        "employeeNumber",
        "employmentStatus",
        "employmentType",
        "endOfProbationPeriodDate",
        "enrollmentCertValidUntilDate",
        "entryDate",
        "exitDate",
        "gender",
        "healthInsuranceName",
        "healthInsuranceType",
        "highestEducationLevel",
        "highestProfessionalEducation",
        "id",
        "incomeTaxClass",
        "lastModifiedDate",
        "marriageStatus",
        "nationalityCountryCode",
        "occupationType",
        "office",
        "placeOfBirth",
        "privateAddress",
        "privateEmailAddress",
        "privatePhoneNumber",
        "religion",
        "salaryType",
        "salutation",
        "socialSecurityNumber",
        "supervisorId",
        "taxNumber",
        "userId",
        "version",
        "workScheduleProfileAssignments",
        "workingTimeRuleAssignments",
    }
)
_NOT_FILTERABLE = frozenset({"privateAddress", "workScheduleProfileAssignments", "workingTimeRuleAssignments"})
# properties of the linked user that weclapp allows in employee filters
_ADDITIONAL_FILTERS = frozenset({"email", "firstName", "fullUserName", "lastName", "title"})


class EmployeesResource(WriteResource[Employee, EmployeeCreate, EmployeeUpdate]):
    """Employees: the HR records, each linked to a user."""

    path = "employee"
    entity_model = Employee
    known_properties: ClassVar[frozenset[str]] = _PROPERTIES
    filterable_properties: ClassVar[frozenset[str]] = (_PROPERTIES - _NOT_FILTERABLE) | _ADDITIONAL_FILTERS

    def for_user(self, user_id: str) -> Employee | None:
        """Returns the employee linked to the user, or ``None`` if the user has no employee record."""
        return self.find_one(Filter.eq("userId", user_id))
