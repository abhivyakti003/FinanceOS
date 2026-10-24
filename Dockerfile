# FinanceOS production image
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APP_ENV=production \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_CLIENT_SHOW_ERROR_DETAILS=false \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0

# pg_dump for backups, curl for the health check
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements-postgres.txt ./
RUN pip install -r requirements.txt -r requirements-postgres.txt

COPY . .

# Run as an unprivileged user
RUN useradd --create-home --uid 1000 financeos \
 && mkdir -p /app/logs /app/backups \
 && chown -R financeos:financeos /app/logs /app/backups
USER financeos

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS http://localhost:8501/_stcore/health || exit 1

CMD ["sh", "-c", "python -m app.database.init_db && streamlit run streamlit_app.py"]
