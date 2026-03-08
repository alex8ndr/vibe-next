FROM python:3.14-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1 \
	MALLOC_ARENA_MAX=2

# Install dependencies first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create data directory (parquet will be downloaded here on first run)
RUN mkdir -p /app/data && chmod +x entrypoint.sh

EXPOSE 8000

CMD ["sh", "entrypoint.sh"]
