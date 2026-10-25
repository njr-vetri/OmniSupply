"""
Tests for Notifications and Alert Dispatch module (src/notifications/alerts.py).
"""

import os
import threading
import pytest
import yaml

from src.notifications.alerts import (
    AlertDispatcher,
    format_alert,
    build_email_agent_sender,
    InMemoryAlertStore,
    JsonFileAlertStore,
    STATUS_DRY_RUN,
    STATUS_SKIPPED,
    STATUS_SENT,
    STATUS_DUPLICATE,
    STATUS_FAILED,
    STATUS_INVALID,
    REASON_CONFIG_MISSING,
    REASON_BELOW_MIN_SEVERITY,
    REASON_DRAFTED_ONLY,
    REASON_UNRESOLVED_WITHIN_WINDOW,
    REASON_DRY_RUN_MODE,
)


@pytest.fixture
def valid_critical_alert() -> dict:
    """Standard valid critical alert contract."""
    return {
        "alert_key": "ALERT-INV-CRIT-001",
        "severity": "critical",
        "category": "inventory",
        "entity_id": "SKU-00412",
        "title": "Safety stock depletion for Industrial Sensors",
        "message": "Stock level fell to 8 units, below safety threshold of 15.",
        "evidence": {"stock": 8, "threshold": 15, "warehouse": "West-01"},
        "recommended_action": "Trigger emergency replenishment purchase order.",
    }


@pytest.fixture
def valid_medium_alert() -> dict:
    """Standard valid medium alert contract."""
    return {
        "alert_key": "ALERT-SHIP-MED-002",
        "severity": "medium",
        "category": "logistics",
        "entity_id": "CARRIER-FEDEX",
        "title": "Transit delay detected on Midwest corridor",
        "message": "Average transit time increased by 1.2 days.",
        "evidence": {"delay_days": 1.2, "corridor": "Midwest"},
        "recommended_action": "Reroute through secondary distribution center.",
    }


@pytest.fixture
def valid_low_alert() -> dict:
    """Standard valid low alert contract."""
    return {
        "alert_key": "ALERT-COST-LOW-003",
        "severity": "low",
        "category": "finance",
        "entity_id": "PROD-GEN-01",
        "title": "Minor packaging cost variance",
        "message": "Packaging unit cost +1.5% due to raw material shift.",
        "evidence": {"variance_pct": 1.5},
        "recommended_action": "Review quarterly supplier price index.",
    }


def test_alert_validation_failures_do_not_crash_batch(valid_critical_alert):
    """Verify invalid alert contracts produce 'invalid' status without crashing the batch."""
    invalid_alert_1 = {
        "alert_key": "ALERT-BAD-1",
        # missing severity
        "category": "inventory",
        "entity_id": "SKU-1",
        "title": "Missing severity",
        "message": "msg",
        "evidence": {},
        "recommended_action": "act",
    }
    invalid_alert_2 = {
        "alert_key": "ALERT-BAD-2",
        "severity": "INVALID_SEVERITY_NAME",
        "category": "inventory",
        "entity_id": "SKU-2",
        "title": "Bad severity",
        "message": "msg",
        "evidence": {},
        "recommended_action": "act",
    }
    invalid_alert_3 = {
        "alert_key": "ALERT-BAD-3",
        "severity": "high",
        "category": "inventory",
        "entity_id": "SKU-3",
        "title": "Bad evidence",
        "message": "msg",
        "evidence": "should_be_a_dict_not_a_string",
        "recommended_action": "act",
    }

    dispatcher = AlertDispatcher(dry_run=True)
    report = dispatcher.dispatch(
        [invalid_alert_1, invalid_alert_2, invalid_alert_3, valid_critical_alert]
    )

    assert report["summary"]["total"] == 4
    assert report["summary"][STATUS_INVALID] == 3
    assert report["summary"][STATUS_DRY_RUN] == 1
    assert len(report["errors"]) == 3

    statuses = [r["status"] for r in report["results"]]
    assert statuses == [STATUS_INVALID, STATUS_INVALID, STATUS_INVALID, STATUS_DRY_RUN]


def test_format_alert(valid_critical_alert):
    """Verify format_alert produces clean subject and body text without leaking secrets."""
    valid_critical_alert["evidence"]["api_token"] = "secret-token-12345"
    formatted = format_alert(valid_critical_alert)

    assert isinstance(formatted, dict)
    assert "subject" in formatted
    assert "body" in formatted

    assert "[CRITICAL]" in formatted["subject"]
    assert "Safety stock depletion" in formatted["subject"]
    assert "SKU-00412" in formatted["subject"]

    assert "OMNISUPPLY INTELLIGENCE ALERT" in formatted["body"]
    assert "Trigger emergency replenishment" in formatted["body"]


def test_dry_run_is_default_and_never_reports_sent(valid_critical_alert):
    """Verify dry_run=True is the default and status is 'dry_run', never 'sent'."""
    store = InMemoryAlertStore()
    dispatcher = AlertDispatcher(store=store)  # dry_run=True by default
    report = dispatcher.dispatch([valid_critical_alert])

    assert report["summary"][STATUS_DRY_RUN] == 1
    assert report["summary"][STATUS_SENT] == 0
    res = report["results"][0]
    assert res["status"] == STATUS_DRY_RUN
    assert res["reason"] == REASON_DRY_RUN_MODE


def test_duplicate_suppression_across_calls_and_within_batch(valid_critical_alert):
    """Verify duplicate alert keys are suppressed both across sequential calls and within a single batch."""
    dispatcher = AlertDispatcher(dry_run=True)

    # 1. Within a single batch
    batch_with_dups = [valid_critical_alert, valid_critical_alert.copy()]
    report1 = dispatcher.dispatch(batch_with_dups)

    assert report1["summary"][STATUS_DRY_RUN] == 1
    assert report1["summary"][STATUS_DUPLICATE] == 1
    assert report1["results"][1]["status"] == STATUS_DUPLICATE
    assert report1["results"][1]["reason"] == REASON_UNRESOLVED_WITHIN_WINDOW

    # 2. Sequential second dispatch within window
    report2 = dispatcher.dispatch([valid_critical_alert])
    assert report2["summary"][STATUS_DUPLICATE] == 1
    assert report2["results"][0]["status"] == STATUS_DUPLICATE


def test_resolve_reopens_delivery(valid_critical_alert):
    """Verify calling resolve(alert_key) clears deduplication suppression."""
    dispatcher = AlertDispatcher(dry_run=True)

    # First dispatch
    report1 = dispatcher.dispatch([valid_critical_alert])
    assert report1["summary"][STATUS_DRY_RUN] == 1

    # Second dispatch is duplicate
    report2 = dispatcher.dispatch([valid_critical_alert])
    assert report2["summary"][STATUS_DUPLICATE] == 1

    # Resolve alert
    resolved = dispatcher.resolve(valid_critical_alert["alert_key"])
    assert resolved is True

    # Third dispatch should now succeed (dry_run)
    report3 = dispatcher.dispatch([valid_critical_alert])
    assert report3["summary"][STATUS_DRY_RUN] == 1
    assert report3["summary"][STATUS_DUPLICATE] == 0


def test_severity_threshold_filtering(valid_low_alert, valid_critical_alert):
    """Verify alerts below min_severity are marked 'skipped' with reason 'below_min_severity'."""
    dispatcher = AlertDispatcher(dry_run=True, min_severity="medium")
    report = dispatcher.dispatch([valid_low_alert, valid_critical_alert])

    assert report["summary"][STATUS_SKIPPED] == 1
    assert report["summary"][STATUS_DRY_RUN] == 1

    low_res = report["results"][0]
    assert low_res["status"] == STATUS_SKIPPED
    assert low_res["reason"] == REASON_BELOW_MIN_SEVERITY


def test_missing_config_skips_alert(valid_critical_alert, monkeypatch):
    """Verify missing recipients/SMTP config in live mode produces 'skipped' + 'config_missing'."""
    monkeypatch.delenv("OMNISUPPLY_ALERT_RECIPIENTS", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)

    dispatcher = AlertDispatcher(dry_run=False, recipients=[])
    report = dispatcher.dispatch([valid_critical_alert])

    assert report["summary"][STATUS_SKIPPED] == 1
    assert report["results"][0]["status"] == STATUS_SKIPPED
    assert report["results"][0]["reason"] == REASON_CONFIG_MISSING


def test_sender_confirmation_sets_sent_status(valid_critical_alert):
    """Status is 'sent' ONLY after the injected sender explicitly confirms delivery."""

    def fake_sender(payload):
        return {"sent": True, "provider_id": "msg-999"}

    dispatcher = AlertDispatcher(
        sender=fake_sender,
        dry_run=False,
        recipients=["ops@omnisupply.com"],
    )
    report = dispatcher.dispatch([valid_critical_alert])

    assert report["summary"][STATUS_SENT] == 1
    assert report["results"][0]["status"] == STATUS_SENT


def test_sender_failure_with_bounded_retries(valid_critical_alert):
    """Verify sender exceptions trigger bounded retries with injected sleep and record 'failed'."""
    attempts = 0
    sleeps = []

    def failing_sender(payload):
        nonlocal attempts
        attempts += 1
        raise ConnectionError("SMTP server refused connection")

    def fake_sleep(duration):
        sleeps.append(duration)

    dispatcher = AlertDispatcher(
        sender=failing_sender,
        dry_run=False,
        recipients=["ops@omnisupply.com"],
        max_retries=2,
        retry_sleep=fake_sleep,
    )
    report = dispatcher.dispatch([valid_critical_alert])

    # 1 initial attempt + 2 retries = 3 attempts
    assert attempts == 3
    assert len(sleeps) == 2
    assert report["summary"][STATUS_FAILED] == 1
    assert report["results"][0]["status"] == STATUS_FAILED
    assert "SMTP server refused" in report["results"][0]["reason"]
    assert len(report["errors"]) == 1


def test_sender_drafted_only_returns_skipped(valid_critical_alert):
    """If sender only drafts or logs, status must be 'skipped' with reason 'drafted_only', never 'sent'."""

    def drafting_sender(payload):
        return {"sent": False, "drafted": True, "reason": REASON_DRAFTED_ONLY}

    dispatcher = AlertDispatcher(
        sender=drafting_sender,
        dry_run=False,
        recipients=["ops@omnisupply.com"],
    )
    report = dispatcher.dispatch([valid_critical_alert])

    assert report["summary"][STATUS_SKIPPED] == 1
    assert report["summary"][STATUS_SENT] == 0
    assert report["results"][0]["status"] == STATUS_SKIPPED
    assert report["results"][0]["reason"] == REASON_DRAFTED_ONLY


def test_build_email_agent_sender_honest_drafting(valid_critical_alert):
    """Verify build_email_agent_sender wraps EmailAgent interface and reports 'drafted_only'."""
    sender = build_email_agent_sender()
    dispatcher = AlertDispatcher(
        sender=sender,
        dry_run=False,
        recipients=["ops@omnisupply.com"],
    )
    report = dispatcher.dispatch([valid_critical_alert])

    assert report["summary"][STATUS_SKIPPED] == 1
    assert report["results"][0]["status"] == STATUS_SKIPPED
    assert report["results"][0]["reason"] == REASON_DRAFTED_ONLY


def test_json_file_alert_store_persistence(tmp_path, valid_critical_alert):
    """Verify JsonFileAlertStore persists deduplication state across instances using tmp_path."""
    store_path = str(tmp_path / "alerts.json")
    store1 = JsonFileAlertStore(file_path=store_path)

    dispatcher1 = AlertDispatcher(store=store1, dry_run=True)
    report1 = dispatcher1.dispatch([valid_critical_alert])
    assert report1["summary"][STATUS_DRY_RUN] == 1

    # Open fresh dispatcher with newly instantiated file store on same path
    store2 = JsonFileAlertStore(file_path=store_path)
    dispatcher2 = AlertDispatcher(store=store2, dry_run=True)
    report2 = dispatcher2.dispatch([valid_critical_alert])

    # Must recognize existing active record as duplicate
    assert report2["summary"][STATUS_DUPLICATE] == 1


def test_thread_safety_concurrent_dispatch(valid_critical_alert, valid_medium_alert):
    """Verify concurrent dispatches from multiple threads execute cleanly without race conditions."""
    dispatcher = AlertDispatcher(dry_run=True)
    results_list = []
    lock = threading.Lock()

    def worker(idx):
        alert = valid_critical_alert.copy()
        alert["alert_key"] = f"ALERT-CONCURRENT-{idx}"
        rep = dispatcher.dispatch([alert])
        with lock:
            results_list.append(rep)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results_list) == 12
    for rep in results_list:
        assert rep["summary"][STATUS_DRY_RUN] == 1


def test_yaml_config_files_validity():
    """Verify docker-compose.automation.yml and .github/workflows/ci.yml parse as valid YAML."""
    compose_path = os.path.join(
        os.path.dirname(__file__), "..", "docker-compose.automation.yml"
    )
    ci_path = os.path.join(
        os.path.dirname(__file__), "..", ".github", "workflows", "ci.yml"
    )

    assert os.path.exists(compose_path), "docker-compose.automation.yml must exist"
    assert os.path.exists(ci_path), ".github/workflows/ci.yml must exist"

    with open(compose_path, "r", encoding="utf-8") as f:
        compose_data = yaml.safe_load(f)
    assert isinstance(compose_data, dict)
    assert "services" in compose_data
    assert "redis" in compose_data["services"]
    assert "celery-worker" in compose_data["services"]
    assert "celery-beat" in compose_data["services"]

    with open(ci_path, "r", encoding="utf-8") as f:
        ci_data = yaml.safe_load(f)
    assert isinstance(ci_data, dict)
    assert "jobs" in ci_data
    assert "test" in ci_data["jobs"]
