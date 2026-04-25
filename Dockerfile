# Python 3.11 barqaror versiyasidan foydalanamiz
FROM python:3.11-slim

# Kerakli tizim paketlarini o'rnatamiz
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Ishchi katalogni belgilaymiz
WORKDIR /app

# Kutubxonalarni nusxalaymiz va o'rnatamiz
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Qolgan barcha fayllarni nusxalaymiz
COPY . .

# Botni ishga tushiramiz
CMD ["python", "main.py"]