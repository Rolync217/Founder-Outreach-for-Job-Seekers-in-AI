FROM python:3.11-slim

WORKDIR /app

# System deps:
#   curl        — dashboard health check
#   libpq-dev   — required to build psycopg2 C extension (psycopg2-binary bundles it,
#                 but some slim images still need the shared lib at runtime)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (cached layer — only rebuilds when requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright's Chromium browser + OS-level dependencies.
# Must run after pip install so the playwright CLI is available.
RUN playwright install chromium --with-deps

# Copy application code
COPY . .

# Ensure reports and .tmp directories exist inside the image;
# they are typically bind-mounted at runtime but we create them as a fallback.
RUN mkdir -p reports .tmp

ENV PYTHONUNBUFFERED=1

CMD ["python", "scheduler.py"]
