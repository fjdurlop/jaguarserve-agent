"""Mock calendar: slots = business hours minus booked appointments. Memory or Postgres backend."""

import re
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from psycopg import errors
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from agent.calendar import Appointment, InvalidBooking, SlotTaken

_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def parse_hours(spec: str) -> tuple[set[int], time, time]:
    """'mon-fri 09:00-17:00' -> ({0..4}, 09:00, 17:00)."""
    m = re.fullmatch(r"\s*(\w{3})-(\w{3})\s+(\d{2}):(\d{2})-(\d{2}):(\d{2})\s*", spec.lower())
    if not m:
        raise ValueError(f"BUSINESS_HOURS must look like 'mon-fri 09:00-17:00', got {spec!r}")
    d0, d1 = _DAYS.index(m[1]), _DAYS.index(m[2])
    return set(range(d0, d1 + 1)), time(int(m[3]), int(m[4])), time(int(m[5]), int(m[6]))


class MockCalendar:
    def __init__(
        self,
        types: list[str],
        business_hours: str,
        tz: str,
        slot_minutes: int = 60,
        lead_hours: int = 2,
        pool: ConnectionPool | None = None,
        now=lambda: datetime.now(UTC),
    ):
        self.types = types
        self.days, self.open, self.close = parse_hours(business_hours)
        self.tz = ZoneInfo(tz)
        self.step = timedelta(minutes=slot_minutes)
        self.lead = timedelta(hours=lead_hours)
        self.pool = pool
        self.now = now
        self._mem: dict[str, Appointment] = {}

    # --- slots -------------------------------------------------------------------------------------
    def _candidates(self, days: int) -> list[datetime]:
        earliest = self.now() + self.lead
        start_day: date = earliest.astimezone(self.tz).date()
        out = []
        for d in range(days + 1):
            day = start_day + timedelta(days=d)
            if day.weekday() not in self.days:
                continue
            t = datetime.combine(day, self.open, self.tz)
            end = datetime.combine(day, self.close, self.tz)
            while t + self.step <= end:
                if t >= earliest:
                    out.append(t)
                t += self.step
        return out

    def list_slots(self, appt_type: str, days: int = 7, limit: int = 8) -> list[datetime]:
        if appt_type not in self.types:
            raise InvalidBooking(f"unknown appointment type; use one of {self.types}")
        taken = self._booked_starts()
        return [s for s in self._candidates(min(days, 30)) if s not in taken][:limit]

    def validate(self, appt_type: str, slot_start: datetime) -> None:
        if appt_type not in self.types:
            raise InvalidBooking(f"unknown appointment type; use one of {self.types}")
        if slot_start.tzinfo is None:
            slot_start = slot_start.replace(tzinfo=self.tz)
        if slot_start not in set(self._candidates(30)):
            raise InvalidBooking("slot is outside business hours or too soon")
        if slot_start in self._booked_starts():
            raise SlotTaken("slot already booked")

    # --- bookings ----------------------------------------------------------------------------------
    def book(self, appt: Appointment) -> Appointment:
        existing = self._by_key(appt.idempotency_key)
        if existing:
            return existing
        self.validate(appt.type, appt.slot_start)
        if self.pool is None:
            self._mem[appt.id] = appt
            return appt
        try:
            with self.pool.connection() as conn:
                conn.execute(
                    "INSERT INTO appointments (id, idempotency_key, session_id, type, slot_start, name, "
                    "contact, product_sku) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        appt.id,
                        appt.idempotency_key,
                        appt.session_id,
                        appt.type,
                        appt.slot_start,
                        appt.name,
                        appt.contact,
                        appt.product_sku,
                    ),
                )
        except errors.UniqueViolation as exc:
            existing = self._by_key(appt.idempotency_key)
            if existing:
                return existing
            raise SlotTaken("slot already booked") from exc
        return appt

    def get(self, appt_id: str) -> Appointment | None:
        if self.pool is None:
            return self._mem.get(appt_id)
        return self._one("SELECT * FROM appointments WHERE id = %s", appt_id)

    def cancel(self, appt_id: str) -> Appointment | None:
        appt = self.get(appt_id)
        if appt is None:
            return None
        if self.pool is None:
            appt.status = "cancelled"
            return appt
        with self.pool.connection() as conn:
            conn.execute("UPDATE appointments SET status = 'cancelled' WHERE id = %s", (appt_id,))
        return self.get(appt_id)

    def _by_key(self, key: str) -> Appointment | None:
        if self.pool is None:
            return next((a for a in self._mem.values() if a.idempotency_key == key), None)
        return self._one("SELECT * FROM appointments WHERE idempotency_key = %s", key)

    def _booked_starts(self) -> set[datetime]:
        if self.pool is None:
            return {a.slot_start for a in self._mem.values() if a.status == "booked"}
        with self.pool.connection() as conn:
            rows = conn.execute(
                "SELECT slot_start FROM appointments WHERE status = 'booked' AND slot_start >= %s",
                (self.now(),),
            ).fetchall()
        return {r[0] for r in rows}

    def _one(self, sql: str, value: str) -> Appointment | None:
        with self.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            row = cur.execute(sql, (value,)).fetchone()
        if not row:
            return None
        row.pop("created_at", None)
        return Appointment(**row)
