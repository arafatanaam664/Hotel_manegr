#!/usr/bin/env bash
# ==============================================
# نظام أثير — تشغيل محلي بأمر واحد (لينكس / ماك / Git-Bash)
# يجهّز كل شيء ثم يشغّل النظام كاملاً على http://localhost:8000
# ==============================================
set -euo pipefail
# انقل دائماً إلى جذر المستودع (يعمل أينما استُدعي منه)
cd "$(cd "$(dirname "$0")/.." && pwd)"

echo "==============================================="
echo "   نظام أثير لإدارة الفنادق — تشغيل محلي"
echo "==============================================="

need() { command -v "$1" >/dev/null 2>&1 || { echo "❌ يلزم تثبيت: $1 — $2"; exit 1; }; }
need python3 "https://www.python.org/downloads/ (اختر 3.11 أو أحدث)"
need node "https://nodejs.org (اختر 20 أو أحدث)"

# 1) بيئة بايثون معزولة + الحزم
if [ ! -d .venv ]; then
  echo "⏳ إنشاء بيئة بايثون معزولة (أول مرة فقط)..."
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
echo "⏳ تثبيت/تحديث حزم بايثون..."
python -m pip install --upgrade pip -q
python -m pip install -q -r backend/requirements.txt

# 2) بناء الواجهة الأمامية (إن لم تُبنَ بعد)
if [ ! -f frontend/dist/index.html ]; then
  echo "⏳ تجهيز الواجهة الأمامية (أول مرة فقط — قد يستغرق دقيقتين)..."
  (cd frontend && npm install --silent && npm run build)
fi

# 3) التشغيل: خادم واحد يقدّم الواجهة والـ API معاً
#    قاعدة البيانات SQLite تُنشأ وتُملأ ببيانات تجريبية تلقائياً عند أول إقلاع.
cd backend
echo ""
echo "==============================================="
echo " ✅ النظام يعمل الآن — افتح المتصفح على:"
echo "    http://localhost:8000"
echo ""
echo " 👤 مستخدم تجريبي: admin"
echo " 🔑 كلمة المرور:   admin123!Change"
echo ""
echo " (للإيقاف: اضغط Ctrl+C)"
echo "==============================================="
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
