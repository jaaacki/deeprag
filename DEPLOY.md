# Deployment Guide

## Docker Container Naming

- **Container name**: `emby-processor`
- **Image**: `emby-processor:latest`
- **Network**: `wpfamilyhub` (aliased to `wpfamilyhubid_default`)
- **Service**: `emby-processor`

## Prerequisites

1. Your NAS must have these containers/networks running:
   - WordPress stack network: `wpfamilyhubid_default`
   - Emby server (check name with `docker ps | grep -i emby`)

## Deployment Steps

### 1. Find Your Emby Container Name

SSH to your NAS and check:
```bash
ssh noonoon@192.168.2.198
docker ps | grep -i emby
```

Look for container name (e.g., `emby`, `emby-server`, `embyserver`)

### 2. Prepare Environment File

Copy `.env.example` to `.env` on your NAS:
```bash
ssh noonoon@192.168.2.198
cd /volume3/docker/emby-processor
nano .env
```

Update these values:
- `EMBY_BASE_URL=http://YOUR-EMBY-CONTAINER-NAME:8096`
- `API_TOKEN=your-wordpress-token`

### 3. Deploy Container

```bash
# Upload project files
cd /volume3/docker/emby-processor
# ... copy all project files here ...

# Build and start
docker compose up -d

# Check logs
docker compose logs -f
```

### 4. Verify Connections

Check that emby-processor can reach:
```bash
# Check WordPress API
docker exec emby-processor curl -s http://wpfamilyhubid_nginx/wp-json/emby/v1/health

# Check Emby API (replace 'emby' with your container name)
docker exec emby-processor curl -s -H "X-Emby-Token: 8223eb1d85c34bb3a33a2cf704336bce" http://emby:8096/System/Info
```

## Network Architecture

```
┌─────────────────────────────────────────────────┐
│  Docker Network: wpfamilyhubid_default          │
├─────────────────────────────────────────────────┤
│                                                 │
│  ┌──────────────┐      ┌─────────────────┐    │
│  │ WordPress    │◄─────┤ emby-processor  │    │
│  │ (nginx)      │ API  │                 │    │
│  └──────────────┘      └────────┬────────┘    │
│                                  │             │
│  ┌──────────────┐               │ Trigger     │
│  │ Emby Server  │◄──────────────┘ Scan        │
│  │              │                              │
│  └──────────────┘                              │
│                                                 │
└─────────────────────────────────────────────────┘
         │                    │
         │                    │
    [Emby Library]       [Watch Folder]
    /volume2/...         /volume3/...
```

## Volume Mounts

- **Watch**: `/volume3/docker/yt_dlp/downloads` → `/watch` (read/write)
- **Destination**: `/volume2/system32/linux/systemd/jpv` → `/destination` (read/write)
- **Config**: `./.env` → `/app/.env` (read-only)

## Troubleshooting

### Container won't start
```bash
docker compose logs emby-processor
```

### Can't connect to WordPress API
```bash
# Check network
docker network inspect wpfamilyhubid_default

# Verify container is on the network
docker inspect emby-processor | grep -A 10 Networks
```

### Can't connect to Emby
```bash
# Verify Emby container name
docker ps | grep -i emby

# Update EMBY_BASE_URL in .env
nano .env
docker compose restart
```

### Files not processing
```bash
# Check watch directory permissions
ls -la /volume3/docker/yt_dlp/downloads

# Check logs
docker compose logs -f --tail 100
```

## Updating the Container

```bash
cd /volume3/docker/emby-processor

# Pull latest code
git pull

# Rebuild and restart
docker compose down
docker compose up -d --build

# Verify
docker compose logs -f
```
