"""Workflow definitions: load/validate the YAML config, validate user input, build the dry-run plan.

Workflows are data. Adding one means editing config/workflows.yaml - no code changes.
Nothing here knows any device API: a step's `request` is either a mapping supplied by the
operator once the interface is confirmed, or the literal string TODO.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .inventory import Inventory
from .redact import is_secret_name

PARAM_TYPES = {"string", "int", "bool", "enum", "ip", "cidr", "hostname", "device"}
RISKS = ("low", "medium", "high")
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
PLACEHOLDER_RE = re.compile(r"\{([a-z][a-z0-9_]*)\}")
HOSTNAME_RE = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
DEFAULT_MAX_LEN = 255


class WorkflowConfigError(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("Invalid workflow configuration:\n - " + "\n - ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Param:
    name: str
    label: str
    type: str
    required: bool = True
    help: str = ""
    default: Any = None
    pattern: str | None = None
    pattern_hint: str = ""
    min: int | None = None
    max: int | None = None
    min_length: int = 0
    max_length: int = DEFAULT_MAX_LEN
    choices: tuple[tuple[str, str], ...] = ()
    ip_version: int | None = None


@dataclass(frozen=True)
class Step:
    id: str
    description: str
    interface: str
    write: bool
    target: str  # template; usually "{device}"
    request: Any  # "TODO" or a mapping


@dataclass(frozen=True)
class Workflow:
    id: str
    platform: str
    title: str
    description: str
    risk: str
    assumption: bool
    params: tuple[Param, ...]
    summary: str
    steps: tuple[Step, ...]
    hash: str = ""
    notes: tuple[str, ...] = ()

    @property
    def device_param(self) -> Param | None:
        return next((p for p in self.params if p.type == "device"), None)


@dataclass(frozen=True)
class Platform:
    id: str
    name: str
    summary: str
    interface_note: str  # candidate interfaces; shown as UNCONFIRMED until the user supplies versions
    version_note: str


@dataclass
class WorkflowCatalog:
    platforms: dict[str, Platform] = field(default_factory=dict)
    workflows: dict[str, Workflow] = field(default_factory=dict)

    def for_platform(self, platform_id: str) -> list[Workflow]:
        return [w for w in self.workflows.values() if w.platform == platform_id]


# ----------------------------------------------------------------------------- loading


def load(path: Path) -> WorkflowCatalog:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    problems: list[str] = []
    catalog = WorkflowCatalog()

    if raw.get("schema_version") != 1:
        problems.append("schema_version must be 1")

    for pid, p in (raw.get("platforms") or {}).items():
        if not isinstance(p, dict) or not p.get("name"):
            problems.append(f"platform {pid}: name is required")
            continue
        catalog.platforms[str(pid)] = Platform(
            id=str(pid),
            name=str(p["name"]),
            summary=str(p.get("summary", "")),
            interface_note=str(p.get("interface_note", "TODO: confirm interface")),
            version_note=str(p.get("version_note", "TODO: confirm software/API version")),
        )

    for i, w in enumerate(raw.get("workflows") or []):
        where = f"workflows[{i}] ({w.get('id', '?') if isinstance(w, dict) else '?'})"
        try:
            wf = _parse_workflow(w, catalog, problems, where)
        except (KeyError, TypeError, ValueError) as exc:
            problems.append(f"{where}: malformed ({exc})")
            continue
        if wf is None:
            continue
        if wf.id in catalog.workflows:
            problems.append(f"{where}: duplicate id")
            continue
        catalog.workflows[wf.id] = wf

    if problems:
        raise WorkflowConfigError(problems)
    return catalog


def _parse_workflow(w: dict, catalog: WorkflowCatalog, problems: list[str], where: str) -> Workflow | None:
    start = len(problems)
    wid = str(w["id"])
    if not ID_RE.match(wid):
        problems.append(f"{where}: id must match {ID_RE.pattern}")
    platform = str(w["platform"])
    if platform not in catalog.platforms:
        problems.append(f"{where}: unknown platform {platform!r}")
    risk = str(w.get("risk", "medium"))
    if risk not in RISKS:
        problems.append(f"{where}: risk must be one of {RISKS}")

    params: list[Param] = []
    for j, p in enumerate(w.get("parameters") or []):
        param = _parse_param(p, problems, f"{where}.parameters[{j}]")
        if param:
            if any(x.name == param.name for x in params):
                problems.append(f"{where}: duplicate parameter {param.name}")
            params.append(param)
    if sum(1 for p in params if p.type == "device") > 1:
        problems.append(f"{where}: at most one device parameter is supported")
    known = {p.name for p in params}

    plan = w.get("plan") or {}
    summary = str(plan.get("summary", ""))
    _check_placeholders(summary, known, problems, f"{where}.plan.summary")
    steps: list[Step] = []
    for k, s in enumerate(plan.get("steps") or []):
        loc = f"{where}.plan.steps[{k}]"
        step = Step(
            id=str(s["id"]),
            description=str(s["description"]),
            interface=str(s["interface"]),
            write=bool(s.get("write", True)),
            target=str(s.get("target", "{device}" if "device" in known else "")),
            request=s.get("request", "TODO"),
        )
        if any(x.id == step.id for x in steps):
            problems.append(f"{loc}: duplicate step id")
        _check_placeholders(step.description, known, problems, loc)
        _check_placeholders(step.target, known, problems, loc)
        if step.request != "TODO":
            if not isinstance(step.request, dict):
                problems.append(f"{loc}: request must be TODO or a mapping")
            else:
                for text in _strings(step.request):
                    _check_placeholders(text, known, problems, loc)
        steps.append(step)
    if not steps:
        problems.append(f"{where}: at least one plan step is required")

    if len(problems) > start:
        return None
    definition = json.dumps(w, sort_keys=True, default=str)
    return Workflow(
        id=wid, platform=platform, title=str(w["title"]), description=str(w.get("description", "")),
        risk=risk, assumption=bool(w.get("assumption", False)), params=tuple(params),
        summary=summary, steps=tuple(steps),
        hash=hashlib.sha256(definition.encode()).hexdigest(),
        notes=tuple(str(n) for n in (w.get("notes") or [])),
    )


def _parse_param(p: dict, problems: list[str], where: str) -> Param | None:
    try:
        name, ptype = str(p["name"]), str(p["type"])
    except (KeyError, TypeError):
        problems.append(f"{where}: name and type are required")
        return None
    if not NAME_RE.match(name):
        problems.append(f"{where}: parameter name {name!r} must match {NAME_RE.pattern}")
    # Device secrets never travel through forms: they come from the secrets store by reference.
    if is_secret_name(name) or ptype in {"secret", "password"}:
        problems.append(f"{where}: {name!r} looks like a secret; secrets must come from the secrets store")
    if ptype not in PARAM_TYPES:
        problems.append(f"{where}: unknown type {ptype!r}")
        return None
    pattern = p.get("pattern")
    if pattern:
        try:
            re.compile(pattern)
        except re.error as exc:
            problems.append(f"{where}: bad pattern ({exc})")
    choices: list[tuple[str, str]] = []
    for c in p.get("choices") or []:
        choices.append((str(c["value"]), str(c.get("label", c["value"]))) if isinstance(c, dict) else (str(c), str(c)))
    if ptype == "enum" and not choices:
        problems.append(f"{where}: enum needs choices")
    return Param(
        name=name, label=str(p.get("label", name)), type=ptype, required=bool(p.get("required", True)),
        help=str(p.get("help", "")), default=p.get("default"), pattern=pattern,
        pattern_hint=str(p.get("pattern_hint", "")), min=p.get("min"), max=p.get("max"),
        min_length=int(p.get("min_length", 0)), max_length=min(int(p.get("max_length", DEFAULT_MAX_LEN)), 1024),
        choices=tuple(choices), ip_version=p.get("ip_version"),
    )


def _check_placeholders(text: str, known: set[str], problems: list[str], where: str) -> None:
    for name in PLACEHOLDER_RE.findall(text):
        if name not in known:
            problems.append(f"{where}: placeholder {{{name}}} is not a defined parameter")


def _strings(node: Any):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v)


# ----------------------------------------------------------------------------- validation


def validate_params(
    wf: Workflow, raw: dict[str, str], inventory: Inventory
) -> tuple[dict[str, Any], dict[str, str]]:
    """Return (clean_values, errors_by_field). Unknown fields are ignored."""
    clean: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for p in wf.params:
        value = raw.get(p.name)
        value = value.strip() if isinstance(value, str) else value
        if p.type == "bool":
            clean[p.name] = value in {"on", "true", "1", "yes", True}
            continue
        if value in (None, ""):
            if p.required:
                errors[p.name] = "This field is required."
            elif p.default is not None:
                clean[p.name] = p.default
            continue
        try:
            clean[p.name] = _validate_one(p, str(value), wf, inventory)
        except ValueError as exc:
            errors[p.name] = str(exc)
    return clean, errors


def _validate_one(p: Param, value: str, wf: Workflow, inventory: Inventory) -> Any:
    if CONTROL_RE.search(value):
        raise ValueError("Control characters are not allowed.")
    if len(value) > p.max_length:
        raise ValueError(f"Use at most {p.max_length} characters.")
    if len(value) < p.min_length:
        raise ValueError(f"Use at least {p.min_length} characters.")
    if p.type == "string":
        if p.pattern and not re.fullmatch(p.pattern, value):
            raise ValueError(p.pattern_hint or "Value is not in the expected format.")
        return value
    if p.type == "int":
        if not re.fullmatch(r"-?\d{1,12}", value):
            raise ValueError("Enter a whole number.")
        n = int(value)
        if p.min is not None and n < p.min:
            raise ValueError(f"Must be at least {p.min}.")
        if p.max is not None and n > p.max:
            raise ValueError(f"Must be at most {p.max}.")
        return n
    if p.type == "enum":
        if value not in {c[0] for c in p.choices}:
            raise ValueError("Choose one of the listed options.")
        return value
    if p.type == "ip":
        try:
            addr = ipaddress.ip_address(value)
        except ValueError:
            raise ValueError("Enter a valid IP address.") from None
        if p.ip_version and addr.version != p.ip_version:
            raise ValueError(f"Enter an IPv{p.ip_version} address.")
        return str(addr)
    if p.type == "cidr":
        try:
            net = ipaddress.ip_network(value, strict=True)
        except ValueError:
            raise ValueError("Enter a valid network in CIDR notation, e.g. 192.0.2.0/24 (host bits must be zero).") from None
        if p.ip_version and net.version != p.ip_version:
            raise ValueError(f"Enter an IPv{p.ip_version} network.")
        return str(net)
    if p.type == "hostname":
        if not HOSTNAME_RE.match(value):
            raise ValueError("Enter a valid hostname.")
        return value
    if p.type == "device":
        dev = inventory.get(value)
        if dev is None or dev.platform != wf.platform:
            raise ValueError("Choose a device from the inventory.")
        return value
    raise ValueError("Unsupported parameter type.")  # pragma: no cover


# ----------------------------------------------------------------------------- planning


def render(template: str, values: dict[str, Any]) -> str:
    """Substitute {name} placeholders only. No attribute access, no format specs."""
    return PLACEHOLDER_RE.sub(lambda m: str(values.get(m.group(1), "")), template)


def _render_request(node: Any, values: dict[str, Any]) -> Any:
    if isinstance(node, str):
        return render(node, values)
    if isinstance(node, dict):
        return {k: _render_request(v, values) for k, v in node.items()}
    if isinstance(node, list):
        return [_render_request(v, values) for v in node]
    return node


def build_plan(wf: Workflow, values: dict[str, Any], inventory: Inventory) -> dict[str, Any]:
    """The dry-run: what the portal intends to do, from parameters alone.

    It does NOT read live device state, so it cannot show a true diff. TODO: per-platform
    read adapters for a real before/after comparison once interfaces are confirmed.
    """
    steps = []
    for s in wf.steps:
        target = render(s.target, values)
        device = inventory.get(target)
        steps.append({
            "id": s.id,
            "description": render(s.description, values),
            "target": target,
            "address": device.address if device else None,
            "interface": s.interface,
            "write": s.write,
            "request_defined": s.request != "TODO",
            "request": None if s.request == "TODO" else _render_request(s.request, values),
        })
    return {
        "summary": render(wf.summary, values) or wf.title,
        "steps": steps,
        "writes": sum(1 for s in steps if s["write"]),
        "unresolved_todo": sum(1 for s in steps if not s["request_defined"]),
        "read_only_note": "Planned from your inputs only; not compared with live device state.",
    }


def plan_hash(plan: dict[str, Any], params: dict[str, Any]) -> str:
    blob = json.dumps({"plan": plan, "params": params}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()
