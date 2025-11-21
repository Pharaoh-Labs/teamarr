FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY api/ ./api/
COPY database/ ./database/
COPY epg/ ./epg/
COPY routes/ ./routes/
COPY scheduler/ ./scheduler/
COPY static/ ./static/
COPY templates/ ./templates/
COPY app.py .
COPY config.py .

# Create directory for data persistence
RUN mkdir -p /app/data

# Expose the application port
EXPOSE 9195

# Set environment variables
ENV FLASK_APP=app.py
ENV PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:9195/health').read()" || exit 1

# Run the application
CMD ["python", "app.py"]
