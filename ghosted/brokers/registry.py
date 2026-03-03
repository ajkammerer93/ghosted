"""Registry for loading and querying broker configurations from YAML."""

from pathlib import Path
from typing import Optional

import yaml

from ghosted.models import BrokerConfig, BrokerMethod


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
