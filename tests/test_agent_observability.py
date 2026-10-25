"""
Tests for Agent Observability module (src/agent_observability/tracing.py).
"""

import json
import threading
import pytest

from src.agent_observability.tracing import (
    AgentTraceRecorder,
    InMemoryTraceStore,
    JsonFileTraceStore,
)


def test_start_run_and_multiple_events():
    """Verify recording multiple events across agents in a single execution run."""
    store = InMemoryTraceStore()
    recorder = AgentTraceRecorder(store=store)
    run_id = recorder.start_run(query="Analyze delay risk for West Coast corridor")

    recorder.record_event(
        run_id=run_id,
        agent_name="data_analyst",
        status="success",
        duration_ms=120.5,
        input_summary="Query SQL shipments",
        output_summary="Found 14 delayed shipments",
    )
    recorder.record_event(
        run_id=run_id,
        agent_name="risk_agent",
        status="success",
        duration_ms=250.0,
        input_summary="Assess corridor risk",
        output_summary="Corridor risk evaluated at 0.45",
    )

    trace = recorder.end_run(run_id)

    assert trace["run_id"] == run_id
    assert trace["status"] == "success"
    assert len(trace["events"]) == 2
    assert trace["totals"]["events_count"] == 2
    assert trace["totals"]["total_duration_ms"] == 370.5
    assert trace["totals"]["success_count"] == 2
    assert trace["ended_at"] is not None


def test_failed_run_inference():
    """Verify end_run marks overall run status as 'failed' if any individual event failed."""
    recorder = AgentTraceRecorder()
    run_id = recorder.start_run(query="Financial variance analysis")

    recorder.record_event(
        run_id=run_id,
        agent_name="finance_agent",
        status="failed",
        duration_ms=80.0,
        error="Database timeout on financial_transactions table",
    )

    trace = recorder.end_run(run_id)
    assert trace["status"] == "failed"
    assert trace["totals"]["failed_count"] == 1


def test_run_auto_creation():
    """Verify record_event auto-registers run if an uninitialized run_id is supplied."""
    recorder = AgentTraceRecorder()
    recorder.record_event(
        run_id="run-auto-123",
        agent_name="supervisor",
        status="success",
        duration_ms=45.0,
    )

    trace = recorder.get_trace("run-auto-123")
    assert trace is not None
    assert trace["run_id"] == "run-auto-123"
    assert len(trace["events"]) == 1
    assert trace["events"][0]["agent_name"] == "supervisor"


def test_unknown_run_id_behavior():
    """Verify handling of non-existent run IDs (get_trace returns None, end_run/to_json raise KeyError)."""
    recorder = AgentTraceRecorder()

    assert recorder.get_trace("non-existent-id") is None

    with pytest.raises(KeyError, match="not found"):
        recorder.end_run("non-existent-id")

    with pytest.raises(KeyError, match="not found"):
        recorder.to_json("non-existent-id")


def test_json_serializability():
    """Verify get_trace output is 100% JSON serializable and loads cleanly."""
    recorder = AgentTraceRecorder()
    run_id = recorder.start_run(query="Evaluate inventory stockouts")

    recorder.record_event(
        run_id=run_id,
        agent_name="risk_agent",
        status="running",
        metadata={"nested": {"count": 10, "ratio": 0.42}},
    )
    recorder.record_event(
        run_id=run_id,
        agent_name="risk_agent",
        status="success",
        duration_ms=100.0,
    )
    recorder.end_run(run_id)

    raw_trace = recorder.get_trace(run_id)
    json_str = json.dumps(raw_trace)
    parsed = json.loads(json_str)

    assert parsed["run_id"] == run_id
    assert parsed["totals"]["events_count"] == 2
    assert recorder.to_json(run_id) == json.dumps(
        raw_trace, indent=2, ensure_ascii=True
    )


def test_redaction_of_sensitive_keys():
    """Verify sensitive keys (passwords, secrets, tokens, api keys) are automatically redacted."""
    recorder = AgentTraceRecorder()
    run_id = recorder.start_run()

    recorder.record_event(
        run_id=run_id,
        agent_name="api_client",
        status="success",
        metadata={
            "OPENAI_API_KEY": "sk-proj-super-secret-12345",
            "db_password": "super_secret_db_pass",
            "auth_token": "bearer-jwt-token-xyz",
            "normal_config": "safe_value",
        },
    )

    trace = recorder.get_trace(run_id)
    event_meta = trace["events"][0]["metadata"]

    assert event_meta["OPENAI_API_KEY"] == "[REDACTED]"
    assert event_meta["db_password"] == "[REDACTED]"
    assert event_meta["auth_token"] == "[REDACTED]"
    assert event_meta["normal_config"] == "safe_value"


def test_rejection_of_chain_of_thought():
    """Verify chain-of-thought and internal reasoning keys are completely rejected and not stored."""
    recorder = AgentTraceRecorder()
    run_id = recorder.start_run()

    recorder.record_event(
        run_id=run_id,
        agent_name="llm_agent",
        status="success",
        metadata={
            "thought": "Thinking about step 1... internal deliberation",
            "chain_of_thought": "User wants delivery report, querying shipments...",
            "reasoning_content": "Alternative hypothesis: carrier delay",
            "cot": "cot trace",
            "safe_metric": 100,
        },
    )

    trace = recorder.get_trace(run_id)
    event_meta = trace["events"][0]["metadata"]

    assert "thought" not in event_meta
    assert "chain_of_thought" not in event_meta
    assert "reasoning_content" not in event_meta
    assert "cot" not in event_meta
    assert event_meta["safe_metric"] == 100


def test_summary_truncation():
    """Verify long summary fields are truncated to 1000 characters."""
    recorder = AgentTraceRecorder()
    run_id = recorder.start_run()

    huge_summary = "A" * 2500
    recorder.record_event(
        run_id=run_id,
        agent_name="logger_agent",
        status="success",
        input_summary=huge_summary,
        output_summary=huge_summary,
    )

    trace = recorder.get_trace(run_id)
    ev = trace["events"][0]

    assert len(ev["input_summary"]) <= 1020
    assert ev["input_summary"].endswith("... [TRUNCATED]")
    assert ev["output_summary"].endswith("... [TRUNCATED]")


def test_thread_safety_concurrent_recording():
    """Verify concurrent record_event calls from multiple threads are thread-safe and lossless."""
    recorder = AgentTraceRecorder()
    run_id = recorder.start_run(query="Multi-threaded stress test")

    num_threads = 10
    events_per_thread = 15

    def worker(thread_idx: int):
        for i in range(events_per_thread):
            recorder.record_event(
                run_id=run_id,
                agent_name=f"agent_{thread_idx}",
                status="success",
                duration_ms=10.0,
                input_summary=f"step {i}",
            )

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    trace = recorder.get_trace(run_id)
    expected_count = num_threads * events_per_thread
    assert len(trace["events"]) == expected_count
    assert trace["totals"]["events_count"] == expected_count
    assert trace["totals"]["success_count"] == expected_count


def test_json_file_store_atomic_roundtrip(tmp_path):
    """Verify JsonFileTraceStore writes atomically, persists to disk, and reads back cleanly."""
    store_dir = str(tmp_path / "traces")
    file_store = JsonFileTraceStore(directory=store_dir)
    recorder = AgentTraceRecorder(store=file_store)

    run_id = recorder.start_run(query="File persistence test")
    recorder.record_event(
        run_id=run_id,
        agent_name="persistence_agent",
        status="success",
        duration_ms=99.0,
    )
    recorder.end_run(run_id)

    # Re-instantiate a fresh store pointing to same directory
    reloaded_store = JsonFileTraceStore(directory=store_dir)
    loaded_trace = reloaded_store.get(run_id)

    assert loaded_trace is not None
    assert loaded_trace["run_id"] == run_id
    assert loaded_trace["status"] == "success"
    assert len(loaded_trace["events"]) == 1

    runs = reloaded_store.list_all()
    assert any(r["run_id"] == run_id for r in runs)


def test_existing_run_not_overwritten():
    """Verify start_run with an existing run_id does not reset existing recorded events."""
    recorder = AgentTraceRecorder()
    run_id = "run-persistent-001"

    recorder.start_run(query="Initial query", run_id=run_id)
    recorder.record_event(run_id=run_id, agent_name="agent_1", status="success")

    # Call start_run again with same run_id
    returned_id = recorder.start_run(query="Different query", run_id=run_id)
    assert returned_id == run_id

    trace = recorder.get_trace(run_id)
    assert len(trace["events"]) == 1
    assert trace["query"] == "Initial query"
