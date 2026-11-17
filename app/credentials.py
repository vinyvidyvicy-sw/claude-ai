"""Device credentials come from the environment or a secrets directory, never from code or the DB.

Lookup for credential_ref "ise-lab" (normalised to ISE_LAB):
  1. env PORTAL_CRED_ISE_LAB_USERNAME / PORTAL_CRED_ISE_LAB_PASSWORD
  2. files <PORTAL_SECRETS_DIR>/ise_lab_username and ise_lab_password
     (Docker/Kubernetes-secret style mounts)
TODO: HashiCorp Vault / CyberArk / cloud secret manager - confirm which store the organisation uses.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping


def _norm(ref: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "_", ref).upper()


@dataclass(frozen=True)
class Credentials:
    username: str = field(repr=False)
    password: str = field(repr=False)

    def __repr__(self) -> str:  # never leak through logging/tracebacks
        return "Credentials(<hidden>)"

    __str__ = __repr__

    def secret_values(self) -> tuple[str, str]:
        return (self.username, self.password)


class CredentialStore:
    def __init__(self, secrets_dir: Path | None, env: Mapping[str, str] | None = None):
        self._dir = secrets_dir
        self._env = os.environ if env is None else env

    def _read(self, ref: str, kind: str) -> str | None:
        key = f"PORTAL_CRED_{_norm(ref)}_{kind.upper()}"
        value = self._env.get(key)
        if value:
            return value
        if self._dir:
            f = self._dir / f"{_norm(ref).lower()}_{kind}"
            try:
                text = f.read_text(encoding="utf-8").rstrip("\r\n")
            except OSError:
                return None
            return text or None
        return None

    def get(self, ref: str) -> Credentials | None:
        user, pw = self._read(ref, "username"), self._read(ref, "password")
        return Credentials(user, pw) if user and pw else None

    def is_configured(self, ref: str) -> bool:
        """Presence check only; the UI shows yes/no and never a value."""
        return self.get(ref) is not None
