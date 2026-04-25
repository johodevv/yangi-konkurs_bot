# ════════════════════════════════════════════════════════
#  Python versiyasi qat'iy 3.11.9 — hech qanday versiya
#  muammosi bo'lmaydi (pydantic-core wheel mavjud)
# ════════════════════════════════════════════════════════
FROM python:3.11.9-slim

# Tizim paketlari (TgCrypto uchun gcc kerak)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Ishchi papka
WORKDIR /app

# Avval requirements — Docker cache uchun (kod o'zgarmasa qayta o'rnatmaydi)
COPY requirements.txt .

# Paketlarni o'rnatish
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Kod fayllarini ko'chirish
COPY . .

# Port (Render $PORT env var ni avtomatik o'rnatadi)
EXPOSE 10000

# Ishga tushirish
CMD ["python", "main.py"]
