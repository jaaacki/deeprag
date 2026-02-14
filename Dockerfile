FROM python:3.12-slim

# Install curl and cron for token refresh
RUN apt-get update && apt-get install -y curl cron && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Setup cron job for token refresh (every 20 hours)
RUN echo "0 */20 * * * /app/scripts/refresh-token-internal.sh >> /app/logs/token-refresh.log 2>&1" | crontab -

# Create logs directory
RUN mkdir -p /app/logs

# Start cron and main application
CMD cron && python main.py
