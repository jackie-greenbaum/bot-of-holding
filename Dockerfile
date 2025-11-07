# Base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy bot code and requirements
COPY . /app

# Upgrade pip and install dependencies
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Expose the port (Render will override with $PORT)
EXPOSE 5000

# Start Hypercorn binding to all interfaces and dynamic port
CMD ["sh", "-c", "hypercorn bot:app --bind 0.0.0.0:${PORT:-5000}"]
