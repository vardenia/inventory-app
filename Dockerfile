FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install dependencies first (layer-caching friendly)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY app.py seed.py ./

# Expose Flask port
EXPOSE 5000

# Production-style launch via gunicorn (falls back to Flask dev server if absent)
CMD ["python", "app.py"]
