FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

# Install system deps (if needed)
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev build-essential && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
ENV PYTHONPATH=/app/src

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
