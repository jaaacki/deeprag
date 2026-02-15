FROM python:3.12-slim

# Install curl, cron, and Docker CLI (for yt-dlp container exec)
RUN apt-get update && apt-get install -y curl cron && rm -rf /var/lib/apt/lists/*

# Install Docker CLI (client only, no daemon)
RUN curl -fsSL https://download.docker.com/linux/static/stable/$(uname -m)/docker-27.5.1.tgz \
    | tar xz --strip-components=1 -C /usr/local/bin docker/docker

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Setup cron job for token refresh (every 20 hours)
RUN echo "0 */20 * * * /app/scripts/refresh-token-internal.sh >> /app/logs/token-refresh.log 2>&1" | crontab -

# Create logs directory
RUN mkdir -p /app/logs

# Make start script executable
RUN chmod +x /app/start.sh

# Expose dashboard port
EXPOSE 8000

# Start cron, API server, and main application
CMD cron && /app/start.sh
