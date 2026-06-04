FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev build-essential curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install poetry==1.8.3
ENV POETRY_NO_INTERACTION=1 \
    POETRY_VENV_IN_PROJECT=1

COPY pyproject.toml ./
RUN poetry install --only main --no-root

COPY . .
ENV PYTHONPATH=/app/src

EXPOSE 8000

CMD ["poetry", "run", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
