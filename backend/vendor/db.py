"""قاعدة بيانات اللوحة — مستقلة كلياً (لا تشارك قاعدة عملاء مطلقاً §1)."""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_vendor_settings


class VendorBase(DeclarativeBase):
    pass


_settings = get_vendor_settings()
engine = create_engine(
    _settings.database_url,
    connect_args={'check_same_thread': False}
    if _settings.database_url.startswith('sqlite') else {})


@event.listens_for(engine, 'connect')
def _fk_pragma(conn, _):
    try:
        cur = conn.cursor()
        cur.execute('PRAGMA foreign_keys=ON')
        cur.close()
    except Exception:
        pass


SessionVendor = sessionmaker(bind=engine, autoflush=False, autocommit=False,
                             future=True)


def get_vdb():
    db = SessionVendor()
    try:
        yield db
    finally:
        db.close()
