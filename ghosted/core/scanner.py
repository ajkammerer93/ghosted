"""Broker scanning logic — search all configured brokers for user data."""

import uuid
from datetime import datetime

from ghosted.brokers.engine import AutomationEngine
from ghosted.models import BrokerConfig, BrokerMethod, ScanReport, ScanResult, UserProfile


async def scan_brokers(
    profile: UserProfile,
    brokers: list[BrokerConfig],
    engine: AutomationEngine,
) -> ScanReport:
    """Scan a list of brokers to check if they hold the user's data.

    Skips phone-only brokers (not scannable via web). Errors on individual
    brokers are caught and logged so the scan continues.
    """
    report = ScanReport(
        scan_id=uuid.uuid4().hex[:12],
        started_at=datetime.now(),
        total_brokers=len(brokers),
    )

    for config in brokers:
        # Phone-only brokers can't be searched
        if config.method == BrokerMethod.PHONE and config.search is None:
            continue

        try:
            result: ScanResult = await engine.search_broker(config, profile)
            report.results.append(result)
            if result.found:
                report.brokers_with_data += 1
            if result.error:
                report.errors += 1
        except Exception as e:
            report.results.append(
                ScanResult(broker_name=config.name, found=False, error=str(e))
            )
            report.errors += 1

    report.completed_at = datetime.now()
    return report
