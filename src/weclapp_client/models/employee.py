"""
Employees (``/employee``): the HR records of weclapp. Name and e-mail address are stored on the linked user.
"""

from enum import StrEnum

from pydantic import Field

from weclapp_client._converters import WeclappDate
from weclapp_client.models.base import WeclappCreateModel, WeclappEntity, WeclappModel, WeclappUpdateModel


class EmploymentStatus(StrEnum):
    """Employment status of an employee."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    LEAVE_OF_ABSENCE = "LEAVE_OF_ABSENCE"
    ONBOARDING = "ONBOARDING"


class WorkScheduleProfileAssignment(WeclappModel):
    """
    A work schedule profile (e.g. full time) that applies to an employee from ``start_date`` on. Usually the start
    date of the first assignment is the entry date of the employee.
    """

    work_schedule_profile_id: str
    start_date: WeclappDate
    end_date: WeclappDate | None = None
    id: str | None = None
    """assigned by weclapp; leave it empty when creating"""


class Employee(WeclappEntity):
    """An employee as returned by weclapp."""

    employee_number: str | None = None
    """assigned by weclapp from its number range, read-only"""
    user_id: str | None = None
    """id of the linked user, which holds name and e-mail address"""
    birth_date: WeclappDate | None = None
    entry_date: WeclappDate | None = None
    """often empty; the start date of the first work schedule profile usually holds the entry date"""
    employment_status: EmploymentStatus | str | None = Field(default=None, union_mode="left_to_right")
    """an :class:`EmploymentStatus`, or the raw value if weclapp introduces a new status"""
    work_schedule_profile_assignments: list[WorkScheduleProfileAssignment] = Field(default_factory=list)


class EmployeeCreate(WeclappCreateModel):
    """The data for creating an employee. Every employee must be linked to a user."""

    user_id: str = Field(min_length=1)
    birth_date: WeclappDate | None = None
    entry_date: WeclappDate | None = None
    work_schedule_profile_assignments: list[WorkScheduleProfileAssignment] | None = None


class EmployeeUpdate(WeclappUpdateModel):
    """Changes of an employee. Only the fields set explicitly are sent."""

    birth_date: WeclappDate | None = None
