@echo off
REM ==============================================
REM نظام أثير — تشغيل محلي بأمر واحد (ويندوز)
REM انقر نقراً مزدوجاً على هذا الملف لتشغيل النظام
REM ==============================================
chcp 65001 >nul
setlocal EnableExtensions
REM انقل دائماً إلى جذر المستودع (يعمل أينما استُدعي منه)
cd /d "%~dp0.."

echo ===============================================
echo    نظام أثير لإدارة الفنادق — تشغيل محلي
echo ===============================================

where python >nul 2>nul
if errorlevel 1 (
  echo  X يلزم تثبيت Python 3.11+ من https://www.python.org/downloads/
  echo     (في أثناء التثبيت فعّل الخيار: Add Python to PATH)
  pause & exit /b 1
)
where node >nul 2>nul
if errorlevel 1 (
  echo  X يلزم تثبيت Node 20+ من https://nodejs.org
  pause & exit /b 1
)

REM 1) بيئة بايثون معزولة + الحزم
if not exist .venv (
  echo  ⏳ إنشاء بيئة بايثون معزولة (أول مرة فقط)...
  python -m venv .venv
  if errorlevel 1 ( echo  X فشل إنشاء البيئة & pause & exit /b 1 )
)
call .venv\Scripts\activate.bat
echo  ⏳ تثبيت/تحديث حزم بايثون...
python -m pip install --upgrade pip -q
python -m pip install -q -r backend\requirements.txt
if errorlevel 1 ( echo  X فشل تثبيت الحزم — افحص اتصال الإنترنت & pause & exit /b 1 )

REM 2) بناء الواجهة الأمامية (إن لم تُبنَ بعد)
if not exist frontend\dist\index.html (
  echo  ⏳ تجهيز الواجهة الأمامية (أول مرة فقط — قد يستغرق دقيقتين)...
  pushd frontend
  call npm install
  call npm run build
  if errorlevel 1 ( popd & echo  X فشل بناء الواجهة & pause & exit /b 1 )
  popd
)

REM 3) التشغيل: خادم واحد يقدّم الواجهة والـ API معاً
cd backend
echo.
echo ===============================================
echo  ✅ النظام يعمل الآن — افتح المتصفح على:
echo     http://localhost:8000
echo.
echo  👤 مستخدم تجريبي: admin
echo  🔑 كلمة المرور:   admin123!Change
echo.
echo  (للإيقاف: أغلق هذه النافذة أو اضغط Ctrl+C)
echo ===============================================
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
pause
