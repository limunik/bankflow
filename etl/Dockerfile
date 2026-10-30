# Образ для загрузчика: тот же рецепт, что у генератора (день 3)
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .