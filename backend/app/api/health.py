"""فحص الصحة — بدون مصادقة (للمراقبة وموازن الحمل)."""
from fastapi import APIRouter

from ..config import get_settings

router = APIRouter(tags=['health'])


@router.get('/api/health')
def health():
    s = get_settings()
    return {'status': 'ok', 'app': s.app_name, 'version': s.version,
            'deployment_mode': s.deployment_mode}
