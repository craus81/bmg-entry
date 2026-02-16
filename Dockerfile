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

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
