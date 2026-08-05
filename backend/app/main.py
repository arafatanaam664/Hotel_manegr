"""تجميع التطبيق (App Factory) — نظام أثير للضيافة.
- مغلّف أخطاء موحد: {"error": {"code": ..., "message_ar": ...}}
- عند توفر بناء الواجهة (frontend/dist) تُقدَّم كتطبيق SPA على نفس المنفذ
- عند الإقلاع: إنشاء الجداول + الزرع الأولي (قابلين للتعطيل بالبيئة)"""
import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import get_settings
from .db import Base, SessionLocal, engine
from .posting import PostingError


class SPAStaticFiles(StaticFiles):
    """StaticFiles مع رجوع لـ index.html (توجيه من جهة العميل)."""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response('index.html', scope)
            raise


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title=s.app_name, version=s.version,
                  docs_url='/api/docs', openapi_url='/api/openapi.json')

    app.add_middleware(
        CORSMiddleware, allow_origins=['*'], allow_credentials=False,
        allow_methods=['*'], allow_headers=['*'])

    # ── مغلّف الأخطاء الموحد ─────────────────────────────
    @app.exception_handler(PostingError)
    async def _posting_err(_: Request, exc: PostingError):
        return JSONResponse(
            status_code=400,
            content={'error': {'code': exc.code, 'message_ar': exc.message}})

    @app.exception_handler(StarletteHTTPException)
    async def _http_err(_: Request, exc: StarletteHTTPException):
        detail = exc.detail
        if isinstance(detail, dict) and 'error' in detail:
            return JSONResponse(status_code=exc.status_code, content=detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={'error': {'code': f'HTTP.{exc.status_code}',
                               'message_ar': str(detail)}})

    @app.exception_handler(RequestValidationError)
    async def _validation_err(_: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        loc = ' → '.join(str(p) for p in first.get('loc', []))
        return JSONResponse(
            status_code=422,
            content={'error': {'code': 'VALIDATION.INVALID_INPUT',
                               'message_ar': 'مدخلات غير صالحة',
                               'detail': f"{loc}: {first.get('msg', '')}",
                               'errors': exc.errors()}})

    # ── الموجِّهات ─────────────────────────────────────
    from .api import accounting, auth, health, hotel, org, pos, reports
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(org.router)
    app.include_router(accounting.router)
    app.include_router(reports.router)
    app.include_router(hotel.router)
    app.include_router(pos.router)

    # ── الإقلاع: جداول + زرع ─────────────────────────────
    @app.on_event('startup')
    def _startup():
        Base.metadata.create_all(engine)
        if s.seed_on_startup:
            db = SessionLocal()
            try:
                from .seed import ensure_hotel_upgrade, seed_if_empty
                if not seed_if_empty(db, tenant_name=s.demo_tenant_name,
                                     admin_username=s.admin_username,
                                     admin_password=s.admin_password)['seeded']:
                    # قاعدة قائمة ← ترقية بدون فقدان (خرائط/غرف/أدوار الفندق)
                    ensure_hotel_upgrade(db)
            finally:
                db.close()

    # ── الواجهة الأمامية (SPA) — أخيراً حتى لا تبتلع /api ──
    dist = os.path.join(os.path.dirname(__file__), '..', '..',
                        'frontend', 'dist')
    dist = os.path.abspath(dist)
    if os.path.isdir(dist):
        app.mount('/', SPAStaticFiles(directory=dist, html=True),
                  name='spa')
    return app


app = create_app()
