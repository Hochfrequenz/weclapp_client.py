"""
The ``/workScheduleProfile`` resource (read-only in this client).
"""

from typing import ClassVar

from weclapp_client.models.work_schedule_profile import WorkScheduleProfile
from weclapp_client.resources.base import ReadResource

# property names according to the weclapp OpenAPI specification (v2)
_PROPERTIES = frozenset(
    {
        "createdDate",
        "description",
        "id",
        "lastModifiedDate",
        "name",
        "type",
        "version",
        "weeklyWorkDays",
        "weeklyWorkDurationInMinutes",
        "workScheduleDays",
    }
)
_NOT_FILTERABLE = frozenset({"workScheduleDays"})


class WorkScheduleProfilesResource(ReadResource[WorkScheduleProfile]):
    """Work schedule profiles, e.g. to check the profile ids that new employees get."""

    path = "workScheduleProfile"
    entity_model = WorkScheduleProfile
    known_properties: ClassVar[frozenset[str]] = _PROPERTIES
    filterable_properties: ClassVar[frozenset[str]] = _PROPERTIES - _NOT_FILTERABLE
