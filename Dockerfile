FROM python:3.11-slim

# Install supervisor and required system dependencies
RUN apt-get update && apt-get install -y supervisor sqlite3 libgl1 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Set up data directory for persistence
ENV DATA_DIR=/data
RUN mkdir -p /data/uploads /data/vector_store
# Ensure the application can write to /data
RUN chmod -R 777 /data

# Default port for Gunicorn
ENV PORT=10000
EXPOSE 10000

# Start supervisor
CMD ["supervisord", "-c", "/app/supervisord.conf"]
