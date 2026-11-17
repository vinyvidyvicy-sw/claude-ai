"""Device inventory, loaded from configuration (never from code)."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

log = logging.getLogger("portal.inventory")
REF_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")


class InventoryError(ValueError):
    pass


@dataclass(frozen=True)
class Device:
    name: str
    platform: str
    address: str  # management address or FQDN; not a secret
    credential_ref: str  # NAME of the credential in the secrets store, never the secret itself


class Inventory:
    def __init__(self, devices: list[Device]):
        self._by_name = {d.name: d for d in devices}

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
            name, platform = str(item["name"]), str(item["platform"])
            address, ref = str(item["address"]), str(item["credential_ref"])
        except (KeyError, TypeError):
            errors.append(f"devices[{i}]: name, platform, address and credential_ref are required")
            continue
        if not NAME_RE.match(name):
            errors.append(f"devices[{i}]: invalid name {name!r}")
        if not REF_RE.match(ref):
            errors.append(f"devices[{i}]: invalid credential_ref {ref!r}")
        if any(d.name == name for d in devices):
            errors.append(f"devices[{i}]: duplicate name {name!r}")
        devices.append(Device(name, platform, address, ref))
    if errors:
        raise InventoryError("; ".join(errors))
    return Inventory(devices)
