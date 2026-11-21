from datetime import UTC, datetime

# Set only by scripts that back-fill history (scripts/seed_week.py) so records get
# the time they are meant to describe. Always None in the API and the monitor.
_frozen: datetime | None = None


def set_clock(value: datetime | None) -> None:
    global _frozen
    _frozen = value


def utcnow() -> datetime:
    return _frozen if _frozen is not None else datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    # SQLite tests omit timezone info on read; PostgreSQL uses TIMESTAMPTZ.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
