FROM python:3.12-slim

# Install curl and Docker CLI (for yt-dlp container exec)
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Install Docker CLI (client only, no daemon)
RUN curl -fsSL https://download.docker.com/linux/static/stable/$(uname -m)/docker-27.5.1.tgz \
    | tar xz --strip-components=1 -C /usr/local/bin docker/docker

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create logs directory
RUN mkdir -p /app/logs

# Make start script executable
RUN chmod +x /app/start.sh

# Expose dashboard port
EXPOSE 8000

# Start API server and main application
CMD /app/start.sh
