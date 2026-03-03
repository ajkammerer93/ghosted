"""Broker scanning logic — search all configured brokers for user data."""

import uuid
from datetime import datetime
from typing import Callable, Optional

from ghosted.brokers.engine import AutomationEngine
from ghosted.models import BrokerConfig, BrokerMethod, ScanReport, ScanResult, ScanStatus, UserProfile


async def scan_brokers(
    profile: UserProfile,
    brokers: list[BrokerConfig],
    engine: AutomationEngine,
    on_broker_start: Optional[Callable[[str, int, int], None]] = None,
    on_broker_done: Optional[Callable[[ScanResult, int, int], None]] = None,
) -> ScanReport:
    """Scan a list of brokers to check if they hold the user's data.

    Skips phone-only brokers (not scannable via web). Errors on individual
    brokers are caught and logged so the scan continues.

    Args:
        on_broker_start: callback(broker_name, current_index, total) called before each broker.
        on_broker_done: callback(result, current_index, total) called after each broker.
    """
    scannable = [
        b for b in brokers
        if b.enabled and not (b.method == BrokerMethod.PHONE and b.search is None)
    ]
    total = len(scannable)

    report = ScanReport(
        scan_id=uuid.uuid4().hex[:12],
        started_at=datetime.now(),
        total_brokers=len(brokers),
    )

    for i, config in enumerate(scannable):
        if on_broker_start:
            on_broker_start(config.name, i + 1, total)

        try:
            result: ScanResult = await engine.search_broker(config, profile)
            report.results.append(result)
            if result.found:
                report.brokers_with_data += 1
            if result.status == ScanStatus.BLOCKED:
                report.brokers_blocked += 1
            elif result.status == ScanStatus.UNKNOWN:
                report.brokers_unknown += 1
            if result.status == ScanStatus.ERROR:
                report.errors += 1
        except Exception as e:
            result = ScanResult(
                broker_name=config.name, status=ScanStatus.ERROR, found=False, error=str(e)
            )
            report.results.append(result)
            report.errors += 1

        if on_broker_done:
            on_broker_done(result, i + 1, total)

    report.completed_at = datetime.now()
    return report
