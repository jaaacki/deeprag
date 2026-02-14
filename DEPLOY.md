# Deployment Guide

## Docker Container Naming

- **Container name**: `emby-processor`
- **Image**: `emby-processor:latest`
- **Networks**:
  - `wpfamilyhubid_net` (WordPress stack)
  - `emby_default` (Emby server)
- **Service**: `emby-processor`

## Prerequisites

1. Your NAS must have these containers/networks running:
   - WordPress stack network: `wpfamilyhubid_net`
   - Emby server network: `emby_default`
   - Emby container: `emby_server`

## Deployment Steps

### 1. Prepare Environment File

Copy `.env.example` to `.env`:
```bash
ssh noonoon@192.168.2.198
cd /volume3/docker/emby-processor
cp .env.example .env
nano .env
```

Update these values:
- `API_TOKEN=your-wordpress-api-token`
- `EMBY_API_KEY=8223eb1d85c34bb3a33a2cf704336bce`

Note: `EMBY_BASE_URL=http://emby_server:8096` is already configured correctly.

### 2. Deploy Container

```bash
# Upload project files
cd /volume3/docker/emby-processor
# ... copy all project files here ...

# Build and start
docker compose up -d

# Check logs
docker compose logs -f
```

### 3. Verify Connections

Check that emby-processor can reach:
```bash
# Check WordPress API
docker exec emby-processor curl -s http://wpfamilyhubid_nginx/wp-json/emby/v1/health

# Check Emby API
docker exec emby-processor curl -s -H "X-Emby-Token: 8223eb1d85c34bb3a33a2cf704336bce" http://emby_server:8096/System/Info
```

## Network Architecture

```
┌─────────────────────────────────────────────────┐
│  Docker Network: wpfamilyhubid_net              │
├─────────────────────────────────────────────────┤
│                                                 │
│  ┌──────────────────┐                          │
│  │ wpfamilyhubid_   │                          │
│  │ nginx            │◄─────┐                   │
│  │ (WordPress)      │ API  │                   │
│  └──────────────────┘      │                   │
│                             │                   │
└─────────────────────────────┼───────────────────┘
                              │
┌─────────────────────────────┼───────────────────┐
│                    ┌────────┴────────┐          │
│                    │ emby-processor  │          │
│                    │ (dual network)  │          │
│                    └────────┬────────┘          │
│                             │                   │
│  ┌──────────────────┐       │ Trigger          │
│  │ emby_server      │◄──────┘ Scan             │
│  │                  │                           │
│  └──────────────────┘                           │
│                                                 │
│  Docker Network: emby_default                   │
└─────────────────────────────────────────────────┘
         │                    │
         │                    │
    [Emby Library]       [Watch Folder]
    /volume2/.../jpv     /volume3/.../downloads
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
docker network inspect wpfamilyhubid_net

# Verify container is on both networks
docker inspect emby-processor | grep -A 20 Networks
```

### Can't connect to Emby
```bash
# Verify Emby server is running
docker ps | grep emby_server

# Check emby_default network
docker network inspect emby_default

# Test connection from processor
docker exec emby-processor curl -s http://emby_server:8096/System/Info
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
