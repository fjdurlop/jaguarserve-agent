"""Calendar adapter interface. The mock is the only implementation until a real provider is chosen."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class BookingError(Exception):
    code = "booking_error"


class SlotTaken(BookingError):
    code = "slot_taken"


class InvalidBooking(BookingError):
    code = "invalid_booking"


@dataclass
class Appointment:
    id: str
    idempotency_key: str
    session_id: str
    type: str
    slot_start: datetime
    name: str
    contact: str
    product_sku: str | None = None
    status: str = "booked"


class Calendar(Protocol):
    types: list[str]

    def list_slots(self, appt_type: str, days: int = 7, limit: int = 8) -> list[datetime]: ...
    def validate(self, appt_type: str, slot_start: datetime) -> None: ...
    def book(self, appt: Appointment) -> Appointment: ...
    def get(self, appt_id: str) -> Appointment | None: ...
    def cancel(self, appt_id: str) -> Appointment | None: ...
