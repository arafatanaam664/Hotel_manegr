#!/usr/bin/env bash
# ==============================================
# نظام أثير — عقدة السحابة (مستقبِل المزامنة، ملف 09)
# نفس الكود بوضع SYNC_RECEIVER_ENABLED — منفذ 8200 افتراضياً.
# يشغَّل بجانب الموقع المحلي (scripts/run.sh على 8000) لتجربة هجينة حية:
#   1) bash scripts/run.sh        (موقع الفندق المحلي)
#   2) bash scripts/run_cloud.sh  (عقدة السحابة)
#   3) من تبويب «مركز المزامنة» بالموقع: اقتران ← رفع أولي ← دفع فوري
# ==============================================
set -euo pipefail
cd "$(cd "$(dirname "$0")/.." && pwd)"

PORT="${CLOUD_PORT:-8200}"
DB_URL="${CLOUD_DATABASE_URL:-sqlite:///./atheer_cloud.db}"
REG_KEY="${SYNC_REGISTER_KEY:-dev-sync-register-key-change-me}"

# shellcheck disable=SC1091
[ -d .venv ] && source .venv/bin/activate

cd backend
echo "==============================================="
echo " ☁ عقدة سحابة أثير (مستقبِل مزامنة) — منفذ ${PORT}"
echo "    قاعدة: ${DB_URL}"
echo "    مفتاح التسجيل: ${REG_KEY}  (تطوير فقط — بدّله بالإنتاج)"
echo "    الاقتران من الموقع: POST /api/sync/pair"
echo "      {\"cloud_url\": \"http://localhost:${PORT}\", \"register_key\": \"...\"}"
echo "==============================================="
export DATABASE_URL="${DB_URL}"
export SYNC_RECEIVER_ENABLED=true
export SYNC_REGISTER_KEY="${REG_KEY}"
export SEED_ON_STARTUP=false   # سحابة نظيفة تُبنى بحزم الاقتران فقط
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT}"
