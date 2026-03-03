"""Shared data models for Ghosted."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class BrokerMethod(str, Enum):
    """How a broker's opt-out process works."""

    WEB_FORM = "web_form"
    EMAIL = "email"
    PHONE = "phone"
    SUPPRESSION_PORTAL = "suppression_portal"


class RemovalStatus(str, Enum):
    """Status of a removal request."""

    PENDING = "pending"
    SUBMITTED = "submitted"
    AWAITING_VERIFICATION = "awaiting_verification"
    VERIFIED = "verified"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    MANUAL_REQUIRED = "manual_required"


class UserProfile(BaseModel):
    """User's personal information stored in the encrypted vault."""

    first_name: str
    last_name: str
    email: str
    city: str
    state: str
    phone: Optional[str] = None
    date_of_birth: Optional[str] = None
    previous_addresses: list[str] = Field(default_factory=list)
    opt_out_email: Optional[str] = None


class BrokerStep(BaseModel):
    """A single step in a broker's opt-out flow."""

    action: str
    url: Optional[str] = None
    selector: Optional[str] = None
    value: Optional[str] = None
    type: Optional[str] = None
    subject_pattern: Optional[str] = None
    link_pattern: Optional[str] = None
    timeout_minutes: Optional[int] = None
    wait_seconds: Optional[float] = None


class BrokerSearchConfig(BaseModel):
    """How to search a broker for user data."""

    url: str
    result_selector: str
    name_selector: str
    no_results_indicator: Optional[str] = None


class BrokerConfig(BaseModel):
    """Configuration for a data broker's opt-out process, loaded from YAML."""

    name: str
    url: str
    opt_out_url: str
    method: BrokerMethod
    parent_company: Optional[str] = None
    captcha: Optional[str] = None
    requires_email_verification: bool = False
    recommended_rescan_days: int = 30
    search: Optional[BrokerSearchConfig] = None
    opt_out_steps: list[BrokerStep] = Field(default_factory=list)
    email_template: Optional[str] = None
    phone_number: Optional[str] = None
    notes: Optional[str] = None


class ScanResult(BaseModel):
    """Result of scanning a single broker for user data."""

    broker_name: str
    profile_url: Optional[str] = None
    info_found: list[str] = Field(default_factory=list)
    found: bool = False
    timestamp: datetime = Field(default_factory=datetime.now)
    error: Optional[str] = None


class RemovalRequest(BaseModel):
    """Tracks the state of a removal request to a broker."""

    broker_name: str
    profile_url: Optional[str] = None
    status: RemovalStatus = RemovalStatus.PENDING
    method: BrokerMethod = BrokerMethod.WEB_FORM
    submitted_at: Optional[datetime] = None
    verified_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    notes: str = ""
    error: Optional[str] = None


class ScanReport(BaseModel):
    """Summary of a full scan across all brokers."""

    scan_id: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    total_brokers: int = 0
    brokers_with_data: int = 0
    results: list[ScanResult] = Field(default_factory=list)
    errors: int = 0


class RemovalReport(BaseModel):
    """Summary of removal operations."""

    total_requests: int = 0
    automated: int = 0
    needs_user_input: int = 0
    manual_only: int = 0
    requests: list[RemovalRequest] = Field(default_factory=list)
