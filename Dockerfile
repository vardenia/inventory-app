FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install dependencies first (layer-caching friendly)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all application source files
COPY app.py db.py models.py seed.py cli.py ./

# Expose Flask port
EXPOSE 5000

# Start the Flask development server.
# For production, replace with: CMD ["gunicorn", "-w", "4", "-b", "0:5000", "app:app"]
CMD ["python", "app.py"]
