"""
Agent Execution Tracing Module.

Thread-safe, privacy-preserving execution recorder for multi-agent workflows.
Captures agent execution sequences, durations, statuses, input/output summaries,
and telemetry. Includes automated redaction of sensitive credentials, truncation
of long payloads, and rejection of chain-of-thought internal reasoning.
"""

import os
import json
import uuid
import tempfile
import threading
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Protocol, runtime_checkable

# Allowed Event Statuses
VALID_EVENT_STATUSES = {"success", "failed", "skipped", "running", "partial"}

# Sensitive key patterns to redact
SENSITIVE_KEY_SUBSTRINGS = (
    "password",
    "secret",
    "token",
    "api_key",
    "authorization",
    "credential",
)

# Forbidden internal reasoning keys (never accepted or stored)
COT_FORBIDDEN_KEYS = (
    "thought",
    "chain_of_thought",
    "reasoning_content",
    "cot",
    "inner_thoughts",
)

MAX_SUMMARY_LENGTH = 1000


def _utc_now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _sanitize_value(val: Any) -> Any:
    """
    Recursively sanitize objects:
    - Redact sensitive keys
    - Filter chain-of-thought keys
    - Truncate strings longer than MAX_SUMMARY_LENGTH
    - Coerce non-serializable objects to string
    """
    if val is None:
        return None

    if isinstance(val, (int, float, bool)):
        return val

    if isinstance(val, str):
        if len(val) > MAX_SUMMARY_LENGTH:
            return val[:MAX_SUMMARY_LENGTH] + "... [TRUNCATED]"
        return val

    if isinstance(val, dict):
        clean_dict = {}
        for k, v in val.items():
            k_str = str(k)
            k_lower = k_str.lower()

            # Reject chain of thought
            if any(forbidden in k_lower for forbidden in COT_FORBIDDEN_KEYS):
                continue

            # Redact secrets
            if any(secret_term in k_lower for secret_term in SENSITIVE_KEY_SUBSTRINGS):
                clean_dict[k_str] = "[REDACTED]"
            else:
                clean_dict[k_str] = _sanitize_value(v)
        return clean_dict

    if isinstance(val, (list, tuple, set)):
        return [_sanitize_value(item) for item in val]

    if hasattr(val, "isoformat"):
        return val.isoformat()

    # Fallback to string coercion for non-serializable types
    val_str = str(val)
    if len(val_str) > MAX_SUMMARY_LENGTH:
        return val_str[:MAX_SUMMARY_LENGTH] + "... [TRUNCATED]"
    return val_str


@runtime_checkable
class TraceStore(Protocol):
    """Protocol defining trace storage backend interface."""

    def save(self, run_id: str, trace_data: Dict[str, Any]) -> None:
        """Persist or update trace data for a given run_id."""
        ...

    def get(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve trace data for a run_id, or None if not found."""
        ...

    def list_all(self) -> List[Dict[str, Any]]:
        """List summary of all recorded runs."""
        ...


class InMemoryTraceStore:
    """Thread-safe in-memory trace storage backend."""

    def __init__(self):
        self._traces: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()

    def save(self, run_id: str, trace_data: Dict[str, Any]) -> None:
        with self._lock:
            self._traces[run_id] = json.loads(json.dumps(trace_data))

    def get(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            data = self._traces.get(run_id)
            if data is None:
                return None
            return json.loads(json.dumps(data))

    def list_all(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [json.loads(json.dumps(t)) for t in self._traces.values()]


class JsonFileTraceStore:
    """
    Atomic file-backed trace storage backend.
    Uses tempfile + os.replace for crash-safe writes.
    """

    def __init__(self, directory: Optional[str] = None):
        env_dir = os.getenv("OMNISUPPLY_TRACE_DIR")
        self.directory = directory or env_dir or "./traces"
        os.makedirs(self.directory, exist_ok=True)
        self._lock = threading.RLock()

    def _file_path(self, run_id: str) -> str:
        # Sanitize run_id for safe filesystem naming
        safe_id = "".join(c for c in run_id if c.isalnum() or c in ("-", "_"))
        return os.path.join(self.directory, f"{safe_id}.json")

    def save(self, run_id: str, trace_data: Dict[str, Any]) -> None:
        with self._lock:
            target_path = self._file_path(run_id)
            target_dir = os.path.dirname(target_path)
            content = json.dumps(trace_data, indent=2, ensure_ascii=True)

            # Atomic write via temp file in the same target directory
            temp_fd, temp_path = tempfile.mkstemp(
                dir=target_dir,
                prefix=f"trace_{run_id[:8]}_",
                suffix=".tmp",
            )
            try:
                with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                    f.write(content)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temp_path, target_path)
            except Exception:
                if os.path.exists(temp_path):
                    try:
                        os.unlink(temp_path)
                    except OSError:
                        pass
                raise

    def get(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            target_path = self._file_path(run_id)
            if not os.path.exists(target_path):
                return None
            try:
                with open(target_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return None

    def list_all(self) -> List[Dict[str, Any]]:
        with self._lock:
            results = []
            if not os.path.exists(self.directory):
                return results
            for fname in os.listdir(self.directory):
                if fname.endswith(".json"):
                    fpath = os.path.join(self.directory, fname)
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            results.append(json.load(f))
                    except Exception:
                        continue
            return results


class AgentTraceRecorder:
    """
    Thread-safe recorder for multi-agent execution traces.

    Maintains execution hierarchy, records execution duration, sanitizes
    credentials, redacts chain-of-thought, and publishes clean JSON traces.
    """

    def __init__(self, store: Optional[TraceStore] = None):
        """
        Initialize AgentTraceRecorder with pluggable store.
        Defaults to InMemoryTraceStore if not provided.
        """
        self.store: TraceStore = store or InMemoryTraceStore()
        self._lock = threading.RLock()

    def start_run(
        self, query: Optional[str] = None, run_id: Optional[str] = None
    ) -> str:
        """
        Start or register a run.
        If run_id is None, generates a new uuid4 string.
        If run_id already exists, returns it without overwriting existing events.
        """
        with self._lock:
            if run_id is None:
                run_id = str(uuid.uuid4())

            existing = self.store.get(run_id)
            if existing is not None:
                return run_id

            clean_query = _sanitize_value(query) if query is not None else None
            now_str = _utc_now_iso()

            trace_data = {
                "run_id": run_id,
                "query": clean_query,
                "started_at": now_str,
                "ended_at": None,
                "status": "running",
                "events": [],
                "totals": {
                    "events_count": 0,
                    "total_duration_ms": 0.0,
                    "success_count": 0,
                    "failed_count": 0,
                    "skipped_count": 0,
                    "running_count": 0,
                    "partial_count": 0,
                },
            }
            self.store.save(run_id, trace_data)
            return run_id

    def record_event(
        self,
        run_id: str,
        agent_name: str,
        status: str,
        duration_ms: Optional[float] = None,
        input_summary: Optional[str] = None,
        output_summary: Optional[str] = None,
        evidence_refs: Optional[List[str]] = None,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Record an agent execution event within a run.
        Auto-creates the run if run_id is not already registered.
        Validates status against standard vocabulary.
        """
        if status not in VALID_EVENT_STATUSES:
            raise ValueError(
                f"Invalid status '{status}'. Must be one of {VALID_EVENT_STATUSES}"
            )

        with self._lock:
            trace = self.store.get(run_id)
            if trace is None:
                self.start_run(run_id=run_id)
                trace = self.store.get(run_id)
                assert trace is not None

            # Sanitize inputs
            clean_input = _sanitize_value(input_summary)
            clean_output = _sanitize_value(output_summary)
            clean_error = _sanitize_value(error)
            clean_metadata = _sanitize_value(metadata) or {}
            clean_evidence = _sanitize_value(evidence_refs) or []
            dur_float = float(duration_ms) if duration_ms is not None else 0.0

            event = {
                "event_id": str(uuid.uuid4()),
                "agent_name": str(agent_name),
                "status": status,
                "timestamp": _utc_now_iso(),
                "duration_ms": dur_float,
                "input_summary": clean_input,
                "output_summary": clean_output,
                "evidence_refs": clean_evidence,
                "error": clean_error,
                "metadata": clean_metadata,
            }

            trace["events"].append(event)

            # Update totals
            totals = trace["totals"]
            totals["events_count"] += 1
            totals["total_duration_ms"] = round(
                totals["total_duration_ms"] + dur_float, 2
            )
            status_key = f"{status}_count"
            if status_key in totals:
                totals[status_key] += 1

            self.store.save(run_id, trace)
            return event

    def end_run(self, run_id: str, status: Optional[str] = None) -> Dict[str, Any]:
        """
        Mark a run as completed.
        Computes final status (defaults to 'failed' if any event failed, else 'success').
        Returns complete trace dictionary.
        """
        with self._lock:
            trace = self.store.get(run_id)
            if trace is None:
                raise KeyError(f"Run ID '{run_id}' not found")

            trace["ended_at"] = _utc_now_iso()

            if status is not None:
                trace["status"] = status
            else:
                # Infer status from events
                has_failed = any(
                    e.get("status") == "failed" for e in trace.get("events", [])
                )
                trace["status"] = "failed" if has_failed else "success"

            self.store.save(run_id, trace)
            return trace

    def get_trace(self, run_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve JSON-serializable trace for run_id.
        Returns None if run_id does not exist.
        """
        with self._lock:
            return self.store.get(run_id)

    def list_runs(self) -> List[Dict[str, Any]]:
        """List summary of all recorded runs."""
        with self._lock:
            return self.store.list_all()

    def to_json(self, run_id: str) -> str:
        """
        Return pretty-formatted JSON string for a run trace.
        Raises KeyError if run_id is unknown.
        """
        trace = self.get_trace(run_id)
        if trace is None:
            raise KeyError(f"Run ID '{run_id}' not found")
        return json.dumps(trace, indent=2, ensure_ascii=True)
