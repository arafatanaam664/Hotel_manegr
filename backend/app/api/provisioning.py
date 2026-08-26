"""واجهات الإعداد التجاري الأول للمستأجر.

هذه الواجهات لا تنشئ بيانات تجريبية ولا تغيّر ملف الترخيص. هي تحفظ اختيار
العميل التشغيلي، وتعيده للواجهة والمعالج ومركز الشركة للمراجعة.
"""
from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import Principal, get_principal, require_perm
from ..audit import audit
from ..provisioning import (DEPLOYMENT_MODES, FEATURE_CATALOG,
                            MODULE_CATALOG, MODULE_DEPENDENCIES,
                            PROPERTY_TYPES, get_or_create, serialize,
                            update_config)
from ..schemas import ProductCatalogOut, ProductConfigIn, ProductConfigOut

router = APIRouter(prefix='/api/setup', tags=['commercial-setup'])


@router.get('/catalog', response_model=ProductCatalogOut)
def catalog():
    return ProductCatalogOut(
        modules=MODULE_CATALOG,
        features=FEATURE_CATALOG,
        dependencies={k: sorted(v) for k, v in MODULE_DEPENDENCIES.items()},
        deployment_modes=sorted(DEPLOYMENT_MODES),
        property_types=sorted(PROPERTY_TYPES),
    )


@router.get('/product', response_model=ProductConfigOut)
def get_product_config(
        db: Session = Depends(get_db),
        pr: Principal = Depends(get_principal)):
    result = ProductConfigOut(**serialize(get_or_create(db, pr.tenant_id)))
    db.commit()
    return result


@router.put('/product', response_model=ProductConfigOut)
def put_product_config(
        body: ProductConfigIn,
        x_installer_token: str | None = Header(default=None, alias='X-Installer-Token'),
        db: Session = Depends(get_db),
        pr: Principal = Depends(get_principal)):
    before = serialize(get_or_create(db, pr.tenant_id))
    result = update_config(
        db, pr.tenant_id, pr.id,
        deployment_mode=body.deployment_mode,
        property_type=body.property_type,
        modules_enabled=body.modules_enabled,
        feature_flags=body.feature_flags,
        multi_branch=body.multi_branch,
        complete=body.complete,
        installer_token=x_installer_token,
        installer_identity=body.installer_identity,
    )
    audit(db, tenant_id=pr.tenant_id, actor_id=pr.id, actor_type='user',
          module='setup', action='PRODUCT_CONFIG_UPDATED',
          entity='tenant_product_config', entity_id=pr.tenant_id,
          before=before, after=result)
    db.commit()
    return ProductConfigOut(**result)
