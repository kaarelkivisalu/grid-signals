# Deploying Grid Signals on Dokploy

## Prerequisites

- A Dokploy instance with a connected server
- Domain name (optional, for HTTPS access)
- API keys: `ENTSOE_API_KEY`, `ANTHROPIC_API_KEY`
- GitHub Personal Access Token (fine-grained, read-only Contents access to this repo)
- (Optional) AWS credentials for S3 backups

## Architecture

The deployment is split into two independent Dokploy services:

- **grid-signals-prefect** (`compose.prefect.yaml`) — Prefect server + worker. Deployed manually/cautiously to avoid killing in-flight flows.
- **grid-signals-app** (`compose.yaml`) — Streamlit UI. Auto-deploys on push to main.

Shared Docker volumes (`grid-data`, `grid-briefings`) connect them. The worker writes data and briefings; Streamlit reads them.

Flow code is **not baked into the worker image**. Instead, the worker clones fresh code from GitHub at the start of each flow run via Prefect's `git_clone` pull step. This means:
- Code changes only need `prefect deploy --all` — no worker restart
- Worker restarts only needed for dependency changes (`pyproject.toml`/`uv.lock`)

```
┌─────────────────────────────────────────────────────┐
│  Dokploy Server                                     │
│                                                     │
│  Dokploy Service: grid-signals-prefect              │
│  (manual deploy)                                    │
│  ┌──────────────────────┐                           │
│  │ prefect-server       │                           │
│  │ :4200                │                           │
│  └──────────────────────┘                           │
│            ▲                                        │
│            │ API                                    │
│  ┌──────────────────────┐                           │
│  │ prefect-worker       │                           │
│  │ (git clone → run)    │──┐                        │
│  └──────────────────────┘  │ shared volumes         │
│                            │                        │
│  Dokploy Service: grid-signals-app                  │
│  (auto-deploy on push)    │                         │
│  ┌──────────────────────┐  │                        │
│  │ streamlit            │──┘                        │
│  │ :8501 (read-only DB) │                           │
│  └──────────────────────┘                           │
│                                                     │
│  Volumes:                                           │
│    grid-data      → /app/data (DuckDB)              │
│    grid-briefings → /app/briefings                  │
│    prefect-data   → Prefect server state            │
└─────────────────────────────────────────────────────┘
```

## Step 1: Create Shared Volumes

SSH into your server and create the external volumes shared between both services:

```bash
docker volume create grid-data
docker volume create grid-briefings
```

## Step 2: Create the Prefect Service in Dokploy

1. In Dokploy UI, click **Create Project** and name it `grid-signals`
2. Inside the project, click **Create Service** → **Compose**
3. Name it `grid-signals-prefect`
4. Set the source to your Git repository
5. Set the **Compose Path** to `./compose.prefect.yaml`
6. **Disable** auto-deploy on push — this service is deployed manually

### Environment Variables

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
```

### Deploy

Click **Deploy**. Wait for the Prefect server healthcheck to pass and the worker to start.

## Step 3: Create the GitHub Access Token Prefect Secret

The worker needs a GitHub PAT to clone the private repo during flow runs.

1. Create a fine-grained GitHub PAT with **read-only Contents** access to this repository
2. Store it as a Prefect Secret block:

```bash
docker compose -f compose.prefect.yaml exec prefect-worker uv run python -c "
from prefect.blocks.system import Secret
Secret(value='ghp_YOUR_TOKEN_HERE').save('github-access-token', overwrite=True)
"
```

## Step 4: Register Flow Deployments

```bash
docker compose -f compose.prefect.yaml exec prefect-worker uv run prefect deploy --all
```

This registers:
- **morning-pipeline** — daily at 05:00 Europe/Tallinn
- **weather-update** — every 6 hours
- **initial-seed** — no schedule (manual trigger only)

## Step 5: Create the Streamlit Service in Dokploy

1. In the same Dokploy project, click **Create Service** → **Compose**
2. Name it `grid-signals-app`
3. Set the source to your Git repository
4. Set the **Compose Path** to `./compose.yaml`
5. **Enable** auto-deploy on push — Streamlit redeploys safely without affecting Prefect

### Environment Variables

```env
ANTHROPIC_API_KEY=your-anthropic-api-key

# Optional: chat cost cap (default $1/day)
CHAT_DAILY_LIMIT_USD=1.0
```

### Deploy

Click **Deploy**.

## Step 6: Configure Domains

### Streamlit UI (port 8501)

1. Go to the `grid-signals-app` service **Domains** tab
2. Add a domain (e.g. `grid.yourdomain.com`)
3. Set **Service Name** to `streamlit` and **Container Port** to `8501`
4. Enable HTTPS (Dokploy handles Let's Encrypt automatically)

### Prefect UI (port 4200) — optional

1. Go to the `grid-signals-prefect` service **Domains** tab
2. Add a domain (e.g. `prefect.yourdomain.com`)
3. Set **Service Name** to `prefect-server` and **Container Port** to `4200`
4. Enable HTTPS
5. **Important:** Add basic auth — the Prefect UI has no built-in authentication

## Step 7: Seed Historical Data

On a fresh deploy the database is empty. The `initial-seed` flow backfills 90 days of data:

```bash
docker compose -f compose.prefect.yaml exec prefect-worker uv run prefect deployment run 'initial-seed/initial-seed'
```

This takes ~20–40 minutes. Monitor progress in the Prefect UI. You only need to run this once.

## Updating Flow Code

After pushing code changes to `main`:

1. Streamlit auto-redeploys via Dokploy (no action needed)
2. Flow code updates automatically — the worker clones fresh code from GitHub at the start of each run
3. If you changed deployment definitions (schedules, parameters) in `prefect.yaml`, re-register:
   ```bash
   docker compose -f compose.prefect.yaml exec prefect-worker uv run prefect deploy --all
   ```

## Updating Dependencies

If `pyproject.toml` or `uv.lock` changed, the worker image needs rebuilding:

1. Wait for any in-flight flows to complete (check Prefect UI)
2. Redeploy `grid-signals-prefect` in Dokploy

The worker has a 120-second graceful shutdown period, so short-running tasks will complete before the container is killed.

## Volumes

| Volume | Purpose | Accessed by |
|--------|---------|-------------|
| `grid-data` | DuckDB database | worker (read-write), streamlit (read-only) |
| `grid-briefings` | Generated briefing files | worker (read-write), streamlit (read-only) |
| `prefect-data` | Prefect server metadata | prefect-server only |

## Troubleshooting

**Worker can't connect to Prefect server:**
Check the `prefect-server` healthcheck is passing. The worker waits for it via `depends_on: condition: service_healthy`.

**DuckDB lock errors in Streamlit:**
The Streamlit service mounts data as read-only (`:ro`). If you still see lock errors, the app has built-in retry logic (3 attempts, 1s delay).

**Flows not running on schedule:**
Make sure you ran `prefect deploy --all` inside the worker container (Step 4). Check the Prefect UI for deployment status.

**Flow run fails with git clone error:**
Verify the GitHub PAT is valid and the Secret block exists:
```bash
docker compose -f compose.prefect.yaml exec prefect-worker uv run python -c "
from prefect.blocks.system import Secret
s = Secret.load('github-access-token')
print('Secret block exists, token starts with:', s.get()[:4])
"
```

**Stuck "Running" flow runs after worker restart:**
Mark orphaned runs as crashed:
```bash
docker compose -f compose.prefect.yaml exec prefect-worker uv run python -c "
from prefect.client.orchestration import get_client
from prefect.states import Crashed
import asyncio

async def fix():
    async with get_client() as client:
        runs = await client.read_flow_runs()
        for run in runs:
            if run.state and run.state.type.value == 'RUNNING':
                print(f'Marking {run.name} ({run.id}) as crashed')
                await client.set_flow_run_state(run.id, Crashed(message='Killed by redeploy'))

asyncio.run(fix())
"
```

**Backup failures:**
Verify AWS credentials are set and the S3 bucket exists:
```bash
docker compose -f compose.prefect.yaml exec prefect-worker aws s3 ls s3://your-bucket/
```
