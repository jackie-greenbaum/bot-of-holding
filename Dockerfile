# Base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy bot code and requirements
COPY . /app

# Install dependencies
RUN pip install --no-cache-dir twitchio flask requests gunicorn

# Expose Flask port
EXPOSE 5000

# Run bot
CMD ["python", "bot.py"]