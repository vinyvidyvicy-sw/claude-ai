"""Device inventory, loaded from configuration (never from code)."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

log = logging.getLogger("portal.inventory")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")


class InventoryError(ValueError):
    pass


@dataclass(frozen=True)
class Device:
    name: str
    platform: str
    address: str  # management address or FQDN; informational, shown to the engineer
    console_url: str | None = None  # optional https:// link to the device's / platform's own console


class Inventory:
    def __init__(self, devices: list[Device], launchers: dict[str, str] | None = None):
        self._by_name = {d.name: d for d in devices}
        self._launchers = dict(launchers or {})

    def set_default_launcher(self, key: str, url: str) -> None:
        """Default address from workflows.yaml; an inventory.yaml `launchers:` entry takes precedence."""
        self._launchers.setdefault(key, url)

    def launch_url(self, platform: str) -> str | None:
        """https URL for a launcher tile (e.g. Ekahau Design), or None if not configured."""
        return self._launchers.get(platform)

    def get(self, name: str) -> Device | None:
        return self._by_name.get(name)

    def for_platform(self, platform: str) -> list[Device]:
        return sorted((d for d in self._by_name.values() if d.platform == platform), key=lambda d: d.name)

    def __len__(self) -> int:
        return len(self._by_name)


def load(path: Path) -> Inventory:
    if not path.exists():
        example = path.with_name("inventory.example.yaml")
        if not example.exists():
            log.warning("inventory file %s not found; starting with an empty inventory", path)
            return Inventory([])
        log.warning("inventory file %s not found; using placeholder %s", path, example.name)
        path = example
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    errors: list[str] = []
    devices: list[Device] = []
    for i, item in enumerate(data.get("devices") or []):
        try:
            name, platform, address = str(item["name"]), str(item["platform"]), str(item["address"])
        except (KeyError, TypeError):
            errors.append(f"devices[{i}]: name, platform and address are required")
            continue
        if "credential_ref" in item:
            log.warning("devices[%d]: credential_ref is ignored; this portal holds no device credentials", i)
        console = item.get("console_url")
        if console is not None and not str(console).startswith("https://"):
            errors.append(f"devices[{i}]: console_url must start with https://")
            console = None
        if not NAME_RE.match(name):
            errors.append(f"devices[{i}]: invalid name {name!r}")
        if any(d.name == name for d in devices):
            errors.append(f"devices[{i}]: duplicate name {name!r}")
        devices.append(Device(name, platform, address, str(console) if console else None))
    if errors:
        raise InventoryError("; ".join(errors))
    launchers: dict[str, str] = {}
    for plat, item in (data.get("launchers") or {}).items():
        url = str((item or {}).get("url", "")) if isinstance(item, dict) else ""
        if not url.startswith("https://"):
            errors.append(f"launchers.{plat}: url must start with https://")
        else:
            launchers[str(plat)] = url
    if errors:
        raise InventoryError("; ".join(errors))
    return Inventory(devices, launchers)
