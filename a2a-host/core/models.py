from pydantic import BaseModel, EmailStr, Field
from typing import List

class MeetingPlan(BaseModel):
    title: str
    start: str     # ISO 8601, e.g. 2025-09-13T16:30:00-07:00
    end: str       # ISO 8601
    attendees: List[EmailStr]
    time_zone: str = Field(description="IANA tz, e.g. America/Los_Angeles")

from typing import Literal

class ScheduleDecision(BaseModel):
    action: Literal["BOOK", "CHECK_FREEBUSY", "ASK_USER"]
    args: dict
    reason: str
