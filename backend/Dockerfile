# نظام أثير — صورة الخادم (إنتاج/محلي) — سياق البناء: جذر المستودع
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app

# الواجهة المبنية تُنسخ بجوار الخادم ليقدّمها كـ SPA على نفس المنفذ
COPY frontend/dist /frontend/dist

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
