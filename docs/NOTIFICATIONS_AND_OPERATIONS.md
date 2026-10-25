# OmniSupply: Notifications & Operations Guide (Person B)

This document specifies the operational configuration, alert dispatch protocol, execution tracing, containerized automation infrastructure, and runtime assumptions for the OmniSupply platform.

---

## 1. Environment Variables Reference

| Variable Name | Required | Default Value | Description |
|---|---|---|---|
| `OMNISUPPLY_ALERT_RECIPIENTS` | Optional | `None` | Comma-separated list of recipient emails for live alert delivery. |
| `OMNISUPPLY_ALERT_STORE_PATH` | Optional | `./omnisupply_alerts.json` | Filesystem path for atomic JSON alert deduplication store. |
| `OMNISUPPLY_TRACE_DIR` | Optional | `./traces` | Filesystem directory for atomic JSON agent execution trace logs. |
| `CELERY_APP` | Optional | `src.automation.celery_app` | Module path to Celery application instance (created in integration phase). |
| `CELERY_LOG_LEVEL` | Optional | `info` | Logging verbosity for Celery worker and beat (`debug`, `info`, `warning`, `error`). |
| `CELERY_BROKER_URL` | Optional | `redis://redis:6379/0` | Celery broker URL (points to Redis service in Compose, or localhost for local testing). |
| `CELERY_RESULT_BACKEND` | Optional | `redis://redis:6379/0` | Celery task result backend URL. |
| `REDIS_PORT` | Optional | `6379` | Host port exposed for Redis container. |
| `DATABASE_URL` | Optional | `postgresql://omnisupply:omnisupply123@host.docker.internal:5432/omnisupply` | External PostgreSQL database connection string. |
| `SMTP_HOST` | Optional | `None` | Outbound SMTP server hostname. |
| `SMTP_PORT` | Optional | `587` | Outbound SMTP server port. |
| `SMTP_USERNAME` | Optional | `None` | Outbound SMTP authentication username. |
| `SMTP_PASSWORD` | Optional | `None` | Outbound SMTP authentication password. |
| `SMTP_FROM` | Optional | `omnisupply@company.com` | Default sender email address. |

---

## 2. Alert Dispatch Protocol & Statuses

The alert dispatch engine (`src/notifications/alerts.py`) enforces strict safety policies, idempotency, and structured status reporting.

### 2.1 Standard Status Vocabulary

Each processed alert returns one of six top-level statuses, with detailed context in a separate `reason` field:

| Top-Level Status | Reason Examples | Meaning |
|---|---|---|
| `dry_run` | `dry_run_mode` | Dry-run is active (default). Alert was evaluated and simulated; no outbound transmission occurred. Recorded in store for deduplication testing. |
| `skipped` | `config_missing` | Missing required recipient or SMTP destination settings. Alert is safely skipped without crashing. |
| `skipped` | `below_min_severity` | Alert severity falls below the configured threshold (e.g. `low` when `min_severity="medium"`). |
| `skipped` | `drafted_only` | Sender generated a drafted notification but confirmed delivery was not executed (e.g., EmailAgent drafting mode). |
| `sent` | `confirmed_delivery` | Sender confirmed explicit outbound transmission. |
| `duplicate` | `unresolved_within_window` | Alert key was dispatched previously within `dedup_window_hours` (default: 24h) and has not been resolved. |
| `failed` | `sender_exception: ...` | Sender adapter raised an unhandled exception or timed out across all bounded retry attempts. Not marked sent in store so retry is possible. |
| `invalid` | `missing_required_field: ...` | Alert contract payload failed schema validation (e.g. empty title, non-dict evidence). |

### 2.2 Dry-Run Behavior

- **Safety First**: `dry_run=True` is the default parameter for `AlertDispatcher`.
- In dry-run mode, no real outbound network calls or SMTP transmissions are made.
- The status is guaranteed to be `dry_run`, never `sent`.
- The alert key is recorded in the alert store, allowing verification of deduplication and idempotency in simulated environments.

### 2.3 Idempotency and Resolution

- **Batch Deduplication**: Duplicate alert keys appearing within the same dispatch batch are collapsed. Only the first is evaluated; subsequent identical keys receive `duplicate` status.
- **Window Deduplication**: By default, an alert key remains suppressed for 24 hours (`dedup_window_hours=24.0`).
- **Resolution**: Calling `dispatcher.resolve(alert_key)` marks an alert as resolved in the store, allowing the anomaly to be notified again if it recurs.

---

## 3. Storage Backends & Atomic Persistence

### 3.1 Alert Store (`AlertStore` Protocol)
- `InMemoryAlertStore`: Thread-safe, non-persistent in-memory dictionary. Ideal for unit tests and stateless microservices.
- `JsonFileAlertStore`: Thread-safe, atomic filesystem persistence. Uses a temporary file (`tempfile.mkstemp`) in the target directory followed by `os.replace` to ensure zero file corruption even during sudden crashes or power loss.

### 3.2 Trace Store (`TraceStore` Protocol)
- `InMemoryTraceStore`: Thread-safe in-memory store for agent execution traces.
- `JsonFileTraceStore`: Atomic file persistence saving `{run_id}.json` traces in `OMNISUPPLY_TRACE_DIR`.

---

## 4. Docker & Celery Automation Operations

### 4.1 Architecture
The automation infrastructure provides asynchronous task processing via Celery and Redis:
- `redis`: In-memory broker and result backend with persistent volume `redis_data`.
- `celery-worker`: Executes background tasks (anomaly detection, supplier scoring, alert generation).
- `celery-beat`: Periodic scheduler triggering tasks at configured cron/interval schedules.
- **External PostgreSQL**: Database access is external to automation containers. On Windows Docker Desktop, containers reach PostgreSQL running on the host via `host.docker.internal:5432` with `extra_hosts` mapping.

### 4.2 Start and Stop Commands

```powershell
# Start Redis broker only (for local test validation)
docker compose -f docker-compose.automation.yml up -d redis

# Verify Redis health
docker compose -f docker-compose.automation.yml ps redis

# Start all automation services (Worker, Beat, Redis)
docker compose -f docker-compose.automation.yml up -d

# Tail Celery worker logs
docker compose -f docker-compose.automation.yml logs -f celery-worker

# Stop all automation services
docker compose -f docker-compose.automation.yml down

# Stop and wipe persistent Redis volume
docker compose -f docker-compose.automation.yml down -v

# Validate compose configuration without launching
docker compose -f docker-compose.automation.yml config
```

---

## 5. Known Operational Limitations & Integration Notes

1. **Email Delivery**: The existing `EmailAgent` (`src/agents/email_agent.py`) implements LLM-based drafting (`draft_emails_node`) producing structured `EmailMessage` models, but does not provide an SMTP transport client. Accordingly, `build_email_agent_sender` reports status `skipped` with reason `drafted_only`. True outbound delivery requires configuring an external SMTP server or injecting a production email gateway.
2. **Celery Application Module**: Person A creates `src/automation/*` during the integration phase. To prevent import errors on this branch, `CELERY_APP` is configured lazily (defaulting to `src.automation.celery_app`) and is evaluated at container runtime, not during image building.
3. **Database Integration**: Neither `scoring.py`, `tracing.py`, nor `alerts.py` directly query or alter database schemas. To persist traces or alerts into PostgreSQL tables (`agent_executions` and `alert_log`), custom `TraceStore` and `AlertStore` adapters can be wired during pipeline orchestration.
