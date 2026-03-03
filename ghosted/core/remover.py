"""Broker removal logic — execute opt-outs for brokers where data was found."""

from datetime import datetime
from typing import Callable, Optional

from ghosted.brokers.engine import AutomationEngine
from ghosted.models import (
    BrokerConfig,
    BrokerMethod,
    RemovalReport,
    RemovalRequest,
    RemovalStatus,
    ScanResult,
    UserProfile,
)


async def remove_from_brokers(
    profile: UserProfile,
    scan_results: list[ScanResult],
    brokers: list[BrokerConfig],
    engine: AutomationEngine,
    on_broker_start: Optional[Callable[[str, int, int], None]] = None,
    on_broker_done: Optional[Callable[[RemovalRequest, int, int], None]] = None,
) -> RemovalReport:
    """Execute removals for every broker where user data was found.

    Routes each broker to the appropriate removal method:
    - web_form / suppression_portal → automated via Playwright
    - email → marked PENDING for the emailer module to send
    - phone → marked MANUAL_REQUIRED
    """
    broker_map = {b.name: b for b in brokers}
    report = RemovalReport()

    actionable = [r for r in scan_results if r.found and r.broker_name in broker_map]
    total = len(actionable)

    for i, result in enumerate(actionable):
        config = broker_map[result.broker_name]

        if on_broker_start:
            on_broker_start(config.name, i + 1, total)

        try:
            request = await _handle_removal(config, profile, result, engine)
        except Exception as e:
            request = RemovalRequest(
                broker_name=config.name,
                profile_url=result.profile_url,
                status=RemovalStatus.FAILED,
                method=config.method,
                error=str(e),
            )

        report.requests.append(request)
        report.total_requests += 1

        match request.status:
            case RemovalStatus.MANUAL_REQUIRED:
                report.manual_only += 1
            case RemovalStatus.FAILED:
                pass  # counted but not categorized
            case RemovalStatus.PENDING:
                report.needs_user_input += 1
            case _:
                report.automated += 1

        if on_broker_done:
            on_broker_done(request, i + 1, total)

    return report


async def _handle_removal(
    config: BrokerConfig,
    profile: UserProfile,
    result: ScanResult,
    engine: AutomationEngine,
) -> RemovalRequest:
    """Route a single broker to the appropriate removal strategy."""
    if config.method in (BrokerMethod.WEB_FORM, BrokerMethod.SUPPRESSION_PORTAL):
        return await engine.execute_removal(config, profile, result.profile_url or "")

    if config.method == BrokerMethod.EMAIL:
        return RemovalRequest(
            broker_name=config.name,
            profile_url=result.profile_url,
            status=RemovalStatus.PENDING,
            method=BrokerMethod.EMAIL,
            notes="Queued for legal demand email",
        )

    # Phone — requires manual intervention
    return RemovalRequest(
        broker_name=config.name,
        profile_url=result.profile_url,
        status=RemovalStatus.MANUAL_REQUIRED,
        method=BrokerMethod.PHONE,
        notes=f"Call {config.phone_number or 'number on website'} to request removal",
    )
