"""
Notifications and Alert Dispatch package for OmniSupply platform.
Provides idempotent, policy-enforced alert dispatch, deduplication, and notification formatting.
"""

from .alerts import (
    AlertDispatcher,
    format_alert,
    build_email_agent_sender,
    AlertStore,
    InMemoryAlertStore,
    JsonFileAlertStore,
    STATUS_DRY_RUN,
    STATUS_SKIPPED,
    STATUS_SENT,
    STATUS_DUPLICATE,
    STATUS_FAILED,
    STATUS_INVALID,
)

__all__ = [
    "AlertDispatcher",
    "format_alert",
    "build_email_agent_sender",
    "AlertStore",
    "InMemoryAlertStore",
    "JsonFileAlertStore",
    "STATUS_DRY_RUN",
    "STATUS_SKIPPED",
    "STATUS_SENT",
    "STATUS_DUPLICATE",
    "STATUS_FAILED",
    "STATUS_INVALID",
]
