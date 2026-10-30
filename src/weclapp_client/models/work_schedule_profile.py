"""
Work schedule profiles (``/workScheduleProfile``): the working times that are assigned to employees, e.g. full time.
"""

from weclapp_client.models.base import WeclappEntity


class WorkScheduleProfile(WeclappEntity):
    """A work schedule profile as returned by weclapp."""

    name: str | None = None
    description: str | None = None
    type: str | None = None
    weekly_work_days: int | None = None
    weekly_work_duration_in_minutes: int | None = None
    """e.g. ``2400`` for 40 hours a week"""
