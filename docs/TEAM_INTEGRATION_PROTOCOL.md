# OmniSupply Team Integration Protocol

## 1. Purpose

This document defines shared interfaces, file ownership, testing expectations, and integration rules for the two developers working on OmniSupply.

The goal is to develop demand forecasting, inventory optimization, supplier intelligence, observability, notifications, and automation independently before integrating them.

## 2. Team Responsibilities

### Person A — Predictive Analytics and Automation

Owns:

- `src/demand_forecasting/`

- `src/inventory_optimization/`

- `src/automation/pipeline.py`

- `src/automation/celery_app.py`

- `src/automation/tasks.py`

- Forecasting, inventory optimization, and pipeline tests.

Person A must not implement or directly import unfinished Person B modules during independent feature development.

### Person B — Supplier Intelligence and Operations

Owns:

- `src/supplier_intelligence/`

- `src/agent_observability/`

- `src/notifications/`

- `.github/workflows/ci.yml`

- `Dockerfile.automation`

- `docker-compose.automation.yml`

- `docs/NOTIFICATIONS_AND_OPERATIONS.md`

- Tests for supplier intelligence, observability, and notifications.

## 3. Shared Interface Contracts

All modules must expose stable, documented interfaces. Use pandas DataFrames for tabular inputs and outputs where appropriate.

### 3.1 Demand Forecasting

Module: `src/demand_forecasting/forecaster.py`

Function:

`forecast_demand(sales_df, item_col="item_id", date_col="date", quantity_col="quantity", horizon_days=30)`

Expected output columns:

- `item_id`

- `forecast_date`

- `predicted_demand`

- `model_name`

Requirements:

- Validate required input columns.

- Handle empty or insufficient historical data explicitly.

- Prevent negative predicted demand.

- Keep forecasting logic deterministic where practical.

- Document assumptions and units.

### 3.2 Inventory Optimization

Module: `src/inventory_optimization/recommender.py`

Function:

`recommend_replenishment(inventory_df, forecasts_df, item_col="item_id", stock_col="current_stock", lead_time_col="lead_time_days", target_cover_days=30)`

Expected output columns:

- `item_id`

- `current_stock`

- `avg_daily_demand`

- `lead_time_demand`

- `safety_stock`

- `reorder_point`

- `recommended_order_qty`

- `estimated_stockout_date`

- `urgency`

- `reason`

Requirements:

- Validate required columns.

- Document assumptions used to calculate safety stock and order quantities.

- Avoid negative order quantities.

- Handle missing inventory or forecast information explicitly.

### 3.3 Supplier Intelligence

Module: `src/supplier_intelligence/`

Function:

`score_suppliers(supplier_metrics_df, supplier_col="supplier_id", metric_columns=None, weights=None)`

Expected output should include:

- `supplier_id`

- `risk_score`

- `risk_level`

- `factor_scores`

- `reasons`

- `data_coverage`

Requirements:

- Document the risk score scale and weighting direction.

- Handle missing metrics transparently.

- Make risk explanations available to downstream reporting.

### 3.4 Agent Observability

Module: `src/agent_observability/`

Provide an `AgentTraceRecorder` interface supporting:

- `start_run(...)`

- `record_event(...)`

- `get_trace(...)`

The implementation must support a local or test-friendly configuration. External observability services must be optional.

### 3.5 Notifications

Module: `src/notifications/`

Notification payloads should support:

- `alert_key`

- `severity`

- `category`

- `entity_id`

- `title`

- `message`

- `evidence`

- `recommended_action`

Requirements:

- Default to dry-run mode.

- Deduplicate repeated unresolved alerts using a stable alert key.

- Do not create purchase orders or make consequential external changes automatically.

- Keep email or other external notification credentials optional for unit tests.

### 3.6 Automation Pipeline

Module: `src/automation/pipeline.py`

Provide:

`run_pipeline(inputs, services, trigger="manual", run_id=None, dry_run=True)`

Requirements:

- Use dependency injection through `services`.

- Coordinate forecasting, inventory recommendations, supplier scoring, tracing, and alerts.

- Avoid tightly coupling the pipeline to a specific external service.

- Return a structured result containing run status, run ID, outputs, alerts, and errors.

- Default to dry-run behavior.

- Require explicit human approval for consequential external actions.

The pipeline must not import unfinished Person B modules directly during independent development. Integration should connect them through injected service implementations.

## 4. File Ownership and Change Rules

1\. Each developer edits only their assigned files during feature development.

2\. Do not overwrite or recreate the existing data layer, API, dashboard, `run_app.py`, or other baseline code.

3\. Do not modify shared dependency files during independent feature development without agreement.

4\. Request review before changing another developer's files.

5\. Coordinate interface changes before implementing them.

6\. Keep commits focused and stage only the files intended for that commit.

7\. Never commit `.env`, API keys, passwords, tokens, or production credentials.

## 5. Git Workflow

1\. Start from an up-to-date `master`.

2\. Create a descriptive feature branch.

3\. Implement one coherent feature at a time.

4\. Run relevant tests before committing and pushing.

5\. Review staged changes with `git diff --cached`.

6\. Push the feature branch and open a pull request into `master`.

7\. Merge only after review and passing checks.

8\. Never push feature work directly to `master`.

Suggested branches:

- `prep/team-contracts`

- `feature/person-a-predictive-automation`

- `feature/person-b-supplier-operations`

- `integration/automation-runtime`

## 6. Testing and Dependencies

- Unit tests must work with synthetic data and mocked external services.

- Core forecasting, inventory, and supplier calculations must not require API keys.

- External integrations must be optional and configurable.

- Do not add dependencies to shared manifests without coordinating with the other developer.

- Apply agreed dependency and lockfile changes during the integration phase.

- Run the existing project tests as well as new tests before merging.

## 7. Integration Sequence

1\. Merge this protocol preparation pull request.

2\. Merge the independent Person A and Person B feature pull requests after review.

3\. Create `integration/automation-runtime`.

4\. Connect the existing project data loaders to forecasting, inventory optimization, and supplier intelligence.

5\. Connect observability and notifications through injected services.

6\. Configure scheduled execution only after agreeing on the scheduler and runtime.

7\. Update the demo entry point and README only during the agreed integration phase.

8\. Run the full test suite and a dry-run end-to-end test.

9\. Require human approval before any real external or purchasing action.

## 8. Open Decisions

The team must confirm these details before integration:

- Actual baseline column names and data schemas.

- Forecasting model and evaluation metrics.

- Safety-stock calculation and service-level assumptions.

- Supplier risk scale and agreed scoring weights.

- Whether Redis, Celery, or another scheduler is already configured.

- The notification channels to enable.

- The tracing backend, if any.

- The required environment variables and optional integrations.

Document decisions in pull requests before changing shared contracts.



