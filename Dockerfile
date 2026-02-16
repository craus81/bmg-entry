# BMG Fleet NetSuite API Service
# Docker container for Railway deployment

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies for thumbnail generation
RUN apt-get update && apt-get install -y --no-install-recommends \
    ghostscript \
    imagemagick \
    poppler-utils \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && sed -i 's/rights="none" pattern="PDF"/rights="read|write" pattern="PDF"/' /etc/ImageMagick-6/policy.xml \
    && sed -i 's/rights="none" pattern="EPS"/rights="read|write" pattern="EPS"/' /etc/ImageMagick-6/policy.xml \
    && sed -i 's/rights="none" pattern="PS"/rights="read|write" pattern="PS"/' /etc/ImageMagick-6/policy.xml \
    && sed -i 's/rights="none" pattern="AI"/rights="read|write" pattern="AI"/' /etc/ImageMagick-6/policy.xml || true

# Install dependencies first (for better caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port (Railway will set PORT env var)
EXPOSE 8000

# Run the application - use shell form to expand $PORT
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
