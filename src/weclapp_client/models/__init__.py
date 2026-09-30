"""
Models of the weclapp entities: read models (as returned by weclapp) and write models (for creating and updating).
"""

from weclapp_client.models.base import WeclappCreateModel, WeclappEntity, WeclappModel, WeclappUpdateModel
from weclapp_client.models.custom_attribute import CustomAttribute, CustomAttributeDefinition, CustomAttributeType
from weclapp_client.models.employee import Employee, EmployeeCreate, EmployeeUpdate, EmploymentStatus
from weclapp_client.models.user import User, UserCreate, UserStatus, UserUpdate

__all__ = [
    "CustomAttribute",
    "CustomAttributeDefinition",
    "CustomAttributeType",
    "Employee",
    "EmployeeCreate",
    "EmployeeUpdate",
    "EmploymentStatus",
    "User",
    "UserCreate",
    "UserStatus",
    "UserUpdate",
    "WeclappCreateModel",
    "WeclappEntity",
    "WeclappModel",
    "WeclappUpdateModel",
]
