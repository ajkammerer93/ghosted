"""Abstract base class for broker plugins."""

from abc import ABC, abstractmethod
from typing import Optional

from ghosted.models import BrokerConfig, BrokerMethod, ScanResult, RemovalRequest, RemovalStatus, UserProfile


class BaseBroker(ABC):
    """Base class that all broker plugins must implement.

    For simple brokers that follow standard patterns, the YAML-driven
    engine handles everything. This class is for brokers that need
    custom logic beyond what YAML can express.
    """

    def __init__(self, config: BrokerConfig):
        self.config = config
        self.name = config.name

    @property
    def method(self) -> BrokerMethod:
        return self.config.method

    @abstractmethod
    async def search(self, profile: UserProfile, page) -> ScanResult:
        """Search this broker for the user's data.

        Args:
            profile: User's personal information.
            page: Playwright page instance.

        Returns:
            ScanResult indicating whether data was found.
        """
        ...

    @abstractmethod
    async def remove(self, profile: UserProfile, page, scan_result: ScanResult) -> RemovalRequest:
        """Execute the opt-out/removal process for this broker.

        Args:
            profile: User's personal information.
            page: Playwright page instance.
            scan_result: Previous scan result with profile URL etc.

        Returns:
            RemovalRequest tracking the status of the removal.
        """
        ...

    def requires_manual_action(self) -> bool:
        """Whether this broker requires manual user action (phone call, ID upload, etc.)."""
        return self.config.method == BrokerMethod.PHONE

    def has_captcha(self) -> bool:
        """Whether this broker's opt-out process includes a CAPTCHA."""
        return self.config.captcha is not None
