"""تجهيز الاختبارات: قاعدة SQLite جديدة لكل اختبار (عزل كامل) + عميل REST."""
import os
import sys

# قبل أي استيراد لوحدات التطبيق: عزل الإعدادات عن بيئة التشغيل
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['SEED_ON_STARTUP'] = 'false'
os.environ['JWT_SECRET'] = 'test-secret-0123456789'

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db import Base, get_db  # noqa: E402
from app.main import create_app  # noqa: E402
from app.seed import seed_if_empty  # noqa: E402

ADMIN = {'username': 'admin', 'password': 'admin123!Change'}


@pytest.fixture()
def db_session(tmp_path):
    """قاعدة ملفية مستقلة لكل اختبار مزروعة بالدليل والخريطة والمستخدم."""
    url = f'sqlite:///{tmp_path}/test.db'
    # timeout مرتفع: اختبارات التزامن تحتاج انتظار القفل لا فشلو الفوري
    engine = create_engine(url, connect_args={'check_same_thread': False,
                                              'timeout': 15})

    @event.listens_for(engine, 'connect')
    def _fk(conn, _):
        cur = conn.cursor()
        cur.execute('PRAGMA foreign_keys=ON')
        cur.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False,
                           future=True)
    db = factory()
    seed = seed_if_empty(db, tenant_name='فندق اختبار',
                         admin_username=ADMIN['username'],
                         admin_password=ADMIN['password'])
    yield db, factory, seed
    db.close()
    engine.dispose()


@pytest.fixture()
def client(db_session):
    """عميل REST مرتبط بقاعدة الاختبار عبر تجاوز الاعتماديات."""
    db, factory, seed = db_session
    app = create_app()

    def override_get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        c.seed_info = seed
        yield c


@pytest.fixture()
def token(client):
    r = client.post('/api/auth/login', json=ADMIN)
    assert r.status_code == 200, r.text
    return r.json()['access_token']


@pytest.fixture()
def auth_hdr(token):
    return {'Authorization': f'Bearer {token}'}
