#!/usr/bin/env bash
# تشغيل لوحة الشركة (منفصل كلياً عن نظام العميل — ملف 08 §1)
# المنفذ 8100، قاعدة vendor_dev.db، سر JWT الخاص بها (VENDOR_* env)
set -e
cd "$(dirname "$0")/.."
PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python
echo "==> لوحة الشركة على http://localhost:8100 (دخول المعاينة: director)"
echo "    رمز TOTP الحالي للمعاينة: $($PY backend/scripts/vendor_totp.py 2>/dev/null || echo 'شغّل backend/scripts/vendor_totp.py')"
cd backend
exec $PY -m uvicorn vendor.main:app --host 0.0.0.0 --port 8100
