#!/usr/bin/env python3
"""أداة الشركة للتراخيص (License Authority — جانب البائع فقط، ملف 07 §1/§2).
المفتاح الخاص لا يغادر بيئة الشركة أبداً؛ هذه الأداة تُشغَّل هناك فقط.

أمثلة:
  # توليد زوج مفاتيح (مرة واحدة — الخاص يُحفظ بعبارة مرور مقسمة/dual control)
  python scripts/license_tool.py gen-keys --out-dir ./authority_keys

  # إصدار/تجديد ترخيص (ربط اختياري ببصمة من ملف activation-request)
  python scripts/license_tool.py issue \\
      --key ./authority_keys/license_private.pem \\
      --tenant-id T-123 --legal-name "فندق المثال" \\
      --package LOCAL --modules ACCOUNTING,HOTEL,POS \\
      --max-users 15 --max-branches 1 --days 365 \\
      --bind-request ./activation_request.json \\
      --license-id LIC-2026-0001 --serial 1 --out ./LIC-2026-0001.license

  # قائمة إلغاء موقعة (إيقاف نهائي = قرار موثق action SUSPEND)
  python scripts/license_tool.py revoke \\
      --key ./authority_keys/license_private.pem \\
      --revocation-serial 3 \\
      --entry serial=1,license_id=LIC-2026-0001,action=SUSPEND \\
      --out ./revocations-3.json
"""
import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                '..')))
from app import licensing as lic  # noqa: E402


def _gen_keys(a):
    os.makedirs(a.out_dir, exist_ok=True)
    priv = lic.gen_private_pem()
    pub = lic.public_pem_from_private(priv)
    pp = os.path.join(a.out_dir, 'license_private.pem')
    xp = os.path.join(a.out_dir, 'license_public.pem')
    with open(pp, 'wb') as f:
        f.write(priv)
    os.chmod(pp, 0o600)
    with open(xp, 'wb') as f:
        f.write(pub)
    print(f'✔ زوج مفاتيح Ed25519:\n  خاص (لا يغادر الشركة!): {pp}\n'
          f'  عام (يُضمَّن في التطبيق): {xp}')


def _issue(a):
    priv = open(a.key, 'rb').read()
    fp = {}
    if a.bind_request:
        req = json.load(open(a.bind_request))
        fp = req.get('hardware_fingerprint') or {}
    expires = date.today() + timedelta(days=a.days)
    payload = {
        'license_id': a.license_id, 'tenant_id': a.tenant_id,
        'legal_name': a.legal_name, 'package': a.package.upper(),
        'modules_enabled': [m.strip().upper() for m in a.modules.split(',')
                            if m.strip()],
        'max_users': a.max_users, 'max_branches': a.max_branches,
        'issued_at': datetime.now(timezone.utc).isoformat(),
        'expires_at': str(expires), 'grace_days': a.grace_days,
        'hardware_fingerprint_hash':
            lic.fingerprint_hash(fp) if fp else None,
        'hardware_fingerprint': fp or None,
        'features_flags': dict(json.loads(a.features))
        if a.features else {},
        'support_level': a.support, 'nonce': os.urandom(16).hex(),
        'serial': a.serial,
    }
    payload['signature'] = lic.sign_payload(payload, priv)
    with open(a.out, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f'✔ ترخيص موقّع حتى {expires} → {a.out}')


def _revoke(a):
    priv = open(a.key, 'rb').read()
    entries = []
    for raw in a.entry:
        e = {}
        for kv in raw.split(','):
            k, v = kv.split('=', 1)
            e[k.strip()] = int(v) if k.strip() == 'serial' else v.strip()
        assert e.get('action') in ('REVOKE', 'SUSPEND', 'SUSPEND_ALL'), \
            'action يجب أن تكون REVOKE أو SUSPEND أو SUSPEND_ALL'
        entries.append(e)
    payload = {'kind': 'REVOCATION_LIST', 'revocation_serial':
               a.revocation_serial,
               'issued_at': datetime.now(timezone.utc).isoformat(),
               'entries': entries, 'nonce': os.urandom(16).hex()}
    payload['signature'] = lic.sign_payload(payload, priv)
    with open(a.out, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f'✔ قائمة إلغاء موقعة (تسلسل {a.revocation_serial}) → {a.out}')


def main():
    p = argparse.ArgumentParser(description='أداة سلطة تراخيص منطق سوفت (سِجِلّ النُّزُل)')
    sub = p.add_subparsers(dest='cmd', required=True)
    g = sub.add_parser('gen-keys')
    g.add_argument('--out-dir', required=True)
    g.set_defaults(fn=_gen_keys)
    i = sub.add_parser('issue')
    i.add_argument('--key', required=True)
    i.add_argument('--tenant-id', required=True)
    i.add_argument('--legal-name', required=True)
    i.add_argument('--package', default='LOCAL',
                   choices=['LOCAL', 'CLOUD', 'HYBRID'])
    i.add_argument('--modules', default=','.join(lic.MODULES_ALL[:6]))
    i.add_argument('--max-users', type=int, default=10)
    i.add_argument('--max-branches', type=int, default=1)
    i.add_argument('--days', type=int, default=365)
    i.add_argument('--grace-days', type=int, default=30)
    i.add_argument('--license-id', required=True)
    i.add_argument('--serial', type=int, required=True)
    i.add_argument('--bind-request', default='')
    i.add_argument('--features', default='')
    i.add_argument('--support', default='STANDARD')
    i.add_argument('--out', required=True)
    i.set_defaults(fn=_issue)
    r = sub.add_parser('revoke')
    r.add_argument('--key', required=True)
    r.add_argument('--revocation-serial', type=int, required=True)
    r.add_argument('--entry', action='append', required=True,
                   help='serial=1,license_id=LIC-x,action=SUSPEND')
    r.add_argument('--out', required=True)
    r.set_defaults(fn=_revoke)
    a = p.parse_args()
    a.fn(a)


if __name__ == '__main__':
    main()
