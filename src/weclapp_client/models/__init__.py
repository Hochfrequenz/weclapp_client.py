"""
Models of the weclapp entities: read models (as returned by weclapp) and write models (for creating and updating).
"""

from weclapp_client.models.base import (
    IdReference,
    WeclappCreateModel,
    WeclappEntity,
    WeclappModel,
    WeclappUpdateModel,
)
from weclapp_client.models.custom_attribute import (
    CustomAttribute,
    CustomAttributeDefinition,
    CustomAttributeListValue,
    CustomAttributeType,
)
from weclapp_client.models.employee import (
    Employee,
    EmployeeCreate,
    EmployeeUpdate,
    EmploymentStatus,
    WorkScheduleProfileAssignment,
)
from weclapp_client.models.user import User, UserCreate, UserStatus, UserUpdate
from weclapp_client.models.work_schedule_profile import WorkScheduleProfile

__all__ = [
    "CustomAttribute",
    "CustomAttributeDefinition",
    "CustomAttributeListValue",
    "CustomAttributeType",
    "Employee",
    "EmployeeCreate",
    "EmployeeUpdate",
    "EmploymentStatus",
    "IdReference",
    "User",
    "UserCreate",
    "UserStatus",
    "UserUpdate",
    "WeclappCreateModel",
    "WeclappEntity",
    "WeclappModel",
    "WeclappUpdateModel",
    "WorkScheduleProfile",
    "WorkScheduleProfileAssignment",
]
