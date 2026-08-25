from app import models as m


def test_product_catalog_is_public_and_has_dependencies(client):
    r = client.get('/api/setup/catalog')
    assert r.status_code == 200, r.text
    body = r.json()
    assert 'ACCOUNTING' in body['modules']
    assert body['dependencies']['POS'] == ['ACCOUNTING']
    assert 'LOCAL' in body['deployment_modes']


def test_owner_can_read_and_update_product_config(client, auth_hdr):
    r = client.get('/api/setup/product', headers=auth_hdr)
    assert r.status_code == 200, r.text
    assert r.json()['setup_state'] == 'COMPLETED'

    r = client.put('/api/setup/product', headers=auth_hdr, json={
        'deployment_mode': 'HYBRID',
        'property_type': 'HOTEL',
        'modules_enabled': ['ACCOUNTING', 'HOTEL', 'POS', 'INVENTORY'],
        'feature_flags': {
            'RESTAURANT': True,
            'POINT_OF_SALE': True,
            'OFFLINE_POS': True,
            'MULTI_CURRENCY': True,
        },
        'multi_branch': True,
        'complete': True,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['deployment_mode'] == 'HYBRID'
    assert body['setup_state'] == 'COMPLETED'
    assert body['feature_flags']['MULTI_BRANCH'] is True
    assert body['feature_flags']['OFFLINE_POS'] is True


def test_product_config_always_keeps_accounting_core(client, auth_hdr):
    r = client.put('/api/setup/product', headers=auth_hdr, json={
        'deployment_mode': 'LOCAL',
        'property_type': 'HOTEL',
        'modules_enabled': ['POS'],
        'feature_flags': {'POINT_OF_SALE': True},
        'multi_branch': False,
        'complete': False,
    })
    assert r.status_code == 200, r.text
    assert r.json()['modules_enabled'] == ['ACCOUNTING', 'POS']


def test_product_config_rejects_feature_without_module(client, auth_hdr):
    r = client.put('/api/setup/product', headers=auth_hdr, json={
        'deployment_mode': 'LOCAL',
        'property_type': 'HOTEL',
        'modules_enabled': ['ACCOUNTING'],
        'feature_flags': {'OFFLINE_POS': True},
        'multi_branch': False,
        'complete': False,
    })
    assert r.status_code == 400, r.text
    assert r.json()['error']['code'] == 'SETUP.FEATURE_DEPENDENCY'


def test_product_config_is_persisted(db_session):
    db, _, seed = db_session
    cfg = db.get(m.TenantProductConfig, seed['tenant_id'])
    assert cfg is not None
    assert 'ACCOUNTING' in cfg.modules_enabled
