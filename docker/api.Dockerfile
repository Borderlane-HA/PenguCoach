FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update -qq && apt-get install -y -qq build-essential libpq-dev && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md alembic.ini ./
COPY apps ./apps
COPY pengucoach ./pengucoach
COPY worker ./worker
COPY db ./db
RUN pip install --no-cache-dir .
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
