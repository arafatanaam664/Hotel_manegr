"""طبقة قاعدة البيانات — SQLAlchemy 2 (Sync من أجل بساطة المعاملات المحاسبية الذرية)."""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from .config import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    url = get_settings().database_url
    connect_args = {}
    if url.startswith('sqlite'):
        connect_args = {'check_same_thread': False}
    eng = create_engine(url, future=True, connect_args=connect_args,
                        pool_pre_ping=True)
    if url.startswith('sqlite'):
        @event.listens_for(eng, 'connect')
        def _sqlite_fk(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute('PRAGMA foreign_keys=ON')
            cur.execute('PRAGMA journal_mode=WAL')
            cur.close()
    return eng


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False,
                            future=True)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
