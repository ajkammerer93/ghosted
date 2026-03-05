"""Registry for loading and querying broker configurations from YAML."""

from pathlib import Path
from typing import Optional

import yaml

from ghosted.models import BrokerConfig, BrokerMethod


def build_broker_patterns(broker_list: list[BrokerConfig], awaiting_names: set[str]) -> dict[str, dict]:
    """Extract email verification patterns from broker configs.

    Returns mapping of broker_name -> {"subject": ..., "link_pattern": ...}
    for brokers that are awaiting verification and have email patterns configured.
    """
    broker_patterns: dict[str, dict] = {}
    for bc in broker_list:
        if bc.name not in awaiting_names:
            continue
        if not bc.requires_email_verification:
            continue
        subject_pat = None
        link_pat = None
        for step in bc.opt_out_steps:
            if step.action == "await_email" and step.subject_pattern:
                subject_pat = step.subject_pattern
            if step.action == "click_email_link" and step.link_pattern:
                link_pat = step.link_pattern
        if subject_pat:
            broker_patterns[bc.name] = {"subject": subject_pat, "link_pattern": link_pat or ""}
    return broker_patterns


class BrokerRegistry:
    """Loads broker configs from a directory of YAML files and provides query methods."""

    def __init__(self, brokers_dir: Path):
        self.brokers_dir = brokers_dir
        self._brokers: dict[str, BrokerConfig] = {}

    def load_all(self) -> list[BrokerConfig]:
        """Load and validate all YAML broker configs from the directory.

        Returns list of successfully loaded configs. Logs warnings for
        files that fail to parse or validate.
        """
        self._brokers.clear()

        if not self.brokers_dir.exists():
            return []

        for yaml_path in sorted(self.brokers_dir.glob("*.yaml")):
            try:
                raw = yaml.safe_load(yaml_path.read_text())
                if raw is None:
                    continue
                config = BrokerConfig.model_validate(raw)
                self._brokers[config.name] = config
            except Exception as e:
                print(f"Warning: failed to load {yaml_path.name}: {e}")

        # Also check .yml extension
        for yaml_path in sorted(self.brokers_dir.glob("*.yml")):
            try:
                raw = yaml.safe_load(yaml_path.read_text())
                if raw is None:
                    continue
                config = BrokerConfig.model_validate(raw)
                if config.name not in self._brokers:
                    self._brokers[config.name] = config
            except Exception as e:
                print(f"Warning: failed to load {yaml_path.name}: {e}")

        return list(self._brokers.values())

    def get_broker(self, name: str) -> Optional[BrokerConfig]:
        """Get a broker config by name. Returns None if not found."""
        return self._brokers.get(name)

    def list_brokers(self) -> list[BrokerConfig]:
        """Return all loaded broker configs."""
        return list(self._brokers.values())

    def get_brokers_by_method(self, method: BrokerMethod) -> list[BrokerConfig]:
        """Return all brokers that use a specific opt-out method."""
        return [b for b in self._brokers.values() if b.method == method]
