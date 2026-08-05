"""ساعة اللوحة الموحدة (UTC نايف — حتمي للتجزئة والتخزين)."""
from datetime import datetime, timezone


def vnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
