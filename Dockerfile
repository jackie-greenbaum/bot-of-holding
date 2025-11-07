# Use Python 3.11 slim base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy bot code and requirements
COPY . /app

# Install dependencies
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir hypercorn

# Expose port (Render sets $PORT)
EXPOSE 10000

# Run bot using Hypercorn for async support
CMD ["hypercorn", "bot:app", "--bind", "0.0.0.0:$PORT", "--workers", "1"]