# Token Auto-Refresh Setup

WordPress JWT tokens expire every 24 hours. This script automatically refreshes them.

## Initial Setup

### 1. Store Refresh Token

Create a `.refresh_token` file in the project root:

```bash
cd /volume3/docker/emby-processor
echo "2b846d290e1e6fd39587a78a9d9cc039f7f978d0b14b2c61ba9d9f9f238ecf2c" > .refresh_token
chmod 600 .refresh_token
```

### 2. Make Script Executable

```bash
chmod +x scripts/refresh-token.sh
```

### 3. Test the Script

```bash
./scripts/refresh-token.sh
```

Should output: `Token refreshed and container restarted`

### 4. Setup Cron Job

Run the refresh script every 20 hours (before 24-hour expiry):

```bash
crontab -e
```

Add this line:

```cron
0 */20 * * * /volume3/docker/emby-processor/scripts/refresh-token.sh >> /volume3/docker/emby-processor/logs/token-refresh.log 2>&1
```

This runs every 20 hours and logs output to `logs/token-refresh.log`.

### 5. Create Log Directory

```bash
mkdir -p logs
```

## How It Works

1. Script reads refresh token from `.refresh_token`
2. Calls WordPress API to get new access token
3. Updates `API_TOKEN` in `.env`
4. Restarts `emby-processor` container
5. Logs the refresh event

## Monitoring

Check refresh logs:

```bash
tail -f logs/token-refresh.log
```

## Troubleshooting

### Token refresh fails

- Check WordPress API is accessible from container network
- Verify refresh token hasn't expired
- Check WordPress JWT plugin settings

### Container doesn't restart

- Verify docker is accessible without sudo
- Check container name is exactly `emby-processor`

## Manual Refresh

If you need to manually refresh:

```bash
cd /volume3/docker/emby-processor
./scripts/refresh-token.sh
```
