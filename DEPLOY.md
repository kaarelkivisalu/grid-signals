# Deploying Grid Signals on Dokploy

## Prerequisites

- A Dokploy instance with a connected server
- Domain name (optional, for HTTPS access)
- API keys: `ENTSOE_API_KEY`, `ANTHROPIC_API_KEY`
- (Optional) AWS credentials for S3 backups

## Step 1: Create the Project in Dokploy

1. In Dokploy UI, click **Create Project** and name it `grid-signals`
2. Inside the project, click **Create Service** → **Compose**
3. Set the source to your Git repository (GitHub, or manual push)
4. Set the **Compose Path** to `./compose.yaml`

## Step 2: Configure Environment Variables

In the Compose service's **Environment** tab, add:

```env
# Required
ENTSOE_API_KEY=your-entsoe-api-key
ANTHROPIC_API_KEY=your-anthropic-api-key

# Optional: S3 backups
S3_BUCKET=your-bucket-name
AWS_ACCESS_KEY_ID=your-aws-key
AWS_SECRET_ACCESS_KEY=your-aws-secret
AWS_DEFAULT_REGION=eu-north-1

# Optional: chat cost cap (default $5/day)
CHAT_DAILY_LIMIT_USD=5.0
```

## Step 3: Configure Domains

In Dokploy, add domains for the services that need external access:

### Streamlit UI (port 8501)

1. Go to the Compose service **Domains** tab
2. Add a domain (e.g. `grid.yourdomain.com`)
3. Set **Service Name** to `streamlit` and **Container Port** to `8501`
4. Enable HTTPS (Dokploy handles Let's Encrypt automatically)

### Prefect UI (port 4200) — optional

If you want remote access to the Prefect dashboard:

1. Add another domain (e.g. `prefect.yourdomain.com`)
2. Set **Service Name** to `prefect-server` and **Container Port** to `4200`
3. Enable HTTPS
4. **Important:** Add basic auth (see Step 5) — the Prefect UI has no built-in authentication

## Step 4: Deploy

Click **Deploy** in Dokploy. It will:

1. Build the Docker image from the `Dockerfile`
2. Start all three services (prefect-server → prefect-worker → streamlit)
3. The worker will register with the Prefect server and start executing scheduled flows

## Step 5: Add Basic Auth (Recommended)

Dokploy supports basic auth on domains via Traefik. To protect the Streamlit and Prefect UIs:

1. In the domain settings for each service, enable **Basic Auth**
2. Set a username and password

This addresses the roadmap item for Streamlit authentication without code changes.

## Step 6: Create Prefect Deployment

After the services are running, register the flow schedules with Prefect:

```bash
# SSH into your server, or use Dokploy's terminal feature
docker compose -f compose.yaml exec prefect-worker uv run prefect deploy --all
```

This reads `prefect.yaml` and registers:
- **morning-pipeline** — daily at 05:00 Europe/Tallinn
- **weather-update** — every 6 hours
- **initial-seed** — no schedule (manual trigger only)

## Step 7: Seed Historical Data

On a fresh deploy the database is empty. The `initial-seed` flow backfills 90 days of ENTSO-E data and weather forecasts in 30-day chunks:

```bash
docker compose -f compose.yaml exec prefect-worker uv run prefect deployment run 'initial-seed/initial-seed'
```

Or trigger it from the Prefect UI under Deployments → initial-seed → Quick Run.

This takes ~20–40 minutes depending on ENTSO-E API response times. You can monitor progress in the Prefect UI. Once complete, the briefing agent and similar-days tool will have enough historical context to produce useful results.

**Note:** You only need to run this once. The daily `morning-pipeline` keeps data current after that.

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Dokploy Server                                 │
│                                                 │
│  ┌──────────────┐   ┌──────────────────────┐    │
│  │ Traefik      │   │ prefect-server       │    │
│  │ (HTTPS+auth) │──▶│ :4200                │    │
│  │              │   └──────────────────────┘    │
│  │              │            ▲                  │
│  │              │            │ API              │
│  │              │   ┌──────────────────────┐    │
│  │              │   │ prefect-worker       │    │
│  │              │   │ (ingestion, briefing │    │
│  │              │   │  backup, health)     │    │
│  │              │   └───────┬──────────────┘    │
│  │              │           │ shared volumes    │
│  │              │   ┌───────┴──────────────┐    │
│  │              │──▶│ streamlit            │    │
│  │              │   │ :8501 (read-only DB) │    │
│  └──────────────┘   └──────────────────────┘    │
│                                                 │
│  Volumes:                                       │
│    grid-data     → /app/data (DuckDB)           │
│    grid-briefings → /app/briefings              │
│    prefect-data  → Prefect server state         │
└─────────────────────────────────────────────────┘
```

## Volumes

| Volume | Purpose | Accessed by |
|--------|---------|-------------|
| `grid-data` | DuckDB database | worker (read-write), streamlit (read-only) |
| `grid-briefings` | Generated briefing files | worker (read-write), streamlit (read-only) |
| `prefect-data` | Prefect server metadata | prefect-server only |

## Key Differences from Local Development

| Aspect | Local | Dokploy |
|--------|-------|---------|
| Data directory | `./data` bind mount | `grid-data` named volume |
| Prefect UI access | `localhost:4200` | Via Traefik with optional auth |
| Streamlit access | `localhost:8501` | Via Traefik with HTTPS + optional auth |
| SSL/TLS | None | Automatic via Let's Encrypt |
| Restarts | Manual | `restart: unless-stopped` |

## Troubleshooting

**Worker can't connect to Prefect server:**
Check the `prefect-server` healthcheck is passing. The worker waits for it via `depends_on: condition: service_healthy`.

**DuckDB lock errors in Streamlit:**
The Streamlit service mounts data as read-only (`:ro`). If you still see lock errors, it means the WAL file is being written. The app has built-in retry logic (3 attempts, 1s delay).

**Flows not running on schedule:**
Make sure you ran `prefect deploy --all` inside the worker container (Step 6). Check the Prefect UI for deployment status.

**Backup failures:**
Verify AWS credentials are set and the S3 bucket exists. Test with:
```bash
docker compose exec prefect-worker aws s3 ls s3://your-bucket/
```
