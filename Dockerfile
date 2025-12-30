FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY src/main.py .
COPY templates/ /app/templates/

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV FLASK_ENV=production

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8383/health || exit 1

# Expose port
EXPOSE 8383

# Run with gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8383", "--workers", "1", "--threads", "2", "main:app"]
