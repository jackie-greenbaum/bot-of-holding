# ---------------- Dockerfile ----------------
# Use a lightweight Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy bot code and requirements
COPY . /app

# Install dependencies
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Expose the port the app runs on
EXPOSE 5000

# Run bot using Hypercorn (async Flask)
CMD ["hypercorn", "bot:app", "--bind", "0.0.0.0:5000"]