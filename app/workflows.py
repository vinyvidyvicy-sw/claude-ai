"""Workflow definitions: load/validate the YAML config, validate user input, build the dry-run plan.

Workflows are data. Adding one means editing config/workflows.yaml - no code changes.
This portal is a front end: it never talks to devices. A workflow's `dispatch` block names the
automation backend and job that perform the change once a request is confirmed (or TODO).
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

from .inventory import Inventory
from .redact import is_secret_name

ICONS = {"shield", "fabric", "cube", "switch-dc", "switch-campus", "search-shield", "server-stack", "wifi", "sparkles", "bulb", "meeting", "rocket", "document", "doc-check", "chart", "gear", "scan", "file", "people", "tools", "search", "person-check", "brain", "gears"}
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
    """A human-readable line of the preview. The portal does not execute steps itself."""
    id: str
    description: str
    write: bool
    target: str  # template; usually "{device}"


@dataclass(frozen=True)
class Dispatch:
    """Where a confirmed request is handed over. The automation backend performs the change."""
    backend: str  # name of a registered backend, or the literal TODO
    job: str  # backend-side job/playbook/template identifier, or TODO
    payload: dict | None  # optional mapping; omitted = pass all validated parameters as-is

    @property
    def defined(self) -> bool:
        return self.backend != "TODO" and self.job != "TODO"


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
    dispatch: Dispatch
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
    interface_note: str  # note shown on the platform page (what the backend will talk to; unconfirmed)
    version_note: str
    console_note: str = ""  # optional hint for the "open console" links
    icon: str = ""  # one of ICONS; drawn in templates/_icons.html
    launcher: bool = False  # tile opens an external tool (URL from inventory.yaml `launchers:`) instead of workflows


@dataclass(frozen=True)
class UseCase:
    """A card on an innovation item's dashboard page. Opens an external dashboard (URL in inventory.yaml `launchers:`)."""
    id: str
    title: str
    summary: str  # short explanation shown on the card
    icon: str = "bulb"
    assumption: bool = False
    category: str = ""  # optional label shown on the card, e.g. an industry
    url: str | None = None  # default https address; inventory.yaml `launchers:` overrides it


@dataclass(frozen=True)
class InnovationItem:
    """An entry under the Inovasi menu. Opens an external page; its https URL is in inventory.yaml `launchers:`."""
    id: str
    title: str
    summary: str
    icon: str = "bulb"
    use_cases: tuple[UseCase, ...] = ()


@dataclass
class WorkflowCatalog:
    platforms: dict[str, Platform] = field(default_factory=dict)
    workflows: dict[str, Workflow] = field(default_factory=dict)
    innovation: dict[str, InnovationItem] = field(default_factory=dict)

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
        if p.get("icon") and p["icon"] not in ICONS:
            problems.append(f"platform {pid}: unknown icon {p['icon']!r} (choose from {sorted(ICONS)})")
        catalog.platforms[str(pid)] = Platform(
            id=str(pid),
            name=str(p["name"]),
            summary=str(p.get("summary", "")),
            interface_note=str(p.get("interface_note", "TODO: confirm interface")),
            version_note=str(p.get("version_note", "TODO: confirm software/API version")),
            console_note=str(p.get("console_note", "")),
            launcher=bool(p.get("launcher", False)),
            icon=str(p.get("icon", "")),
        )

    used_ids: set[str] = set(catalog.platforms)
    for i, it in enumerate(raw.get("innovation") or []):
        try:
            item = InnovationItem(id=str(it["id"]), title=str(it["title"]), summary=str(it.get("summary", "")),
                                  icon=str(it.get("icon", "bulb")))
        except (KeyError, TypeError):
            problems.append(f"innovation[{i}]: id and title are required")
            continue
        if not ID_RE.match(item.id):
            problems.append(f"innovation[{i}]: id must match {ID_RE.pattern}")
        if item.icon not in ICONS:
            problems.append(f"innovation[{i}]: unknown icon {item.icon!r}")
        if item.id in catalog.innovation or item.id in catalog.platforms:
            problems.append(f"innovation[{i}]: duplicate id {item.id!r}")
        ucs = []
        for j, uc in enumerate(it.get("use_cases") or []):
            try:
                u = UseCase(id=str(uc["id"]), title=str(uc["title"]), summary=str(uc.get("summary", "")),
                            icon=str(uc.get("icon", "bulb")), assumption=bool(uc.get("assumption", False)),
                            category=str(uc.get("category", "")), url=str(uc["url"]) if uc.get("url") else None)
            except (KeyError, TypeError):
                problems.append(f"innovation[{i}].use_cases[{j}]: id and title are required")
                continue
            if not ID_RE.match(u.id):
                problems.append(f"innovation[{i}].use_cases[{j}]: id must match {ID_RE.pattern}")
            if u.icon not in ICONS:
                problems.append(f"innovation[{i}].use_cases[{j}]: unknown icon {u.icon!r}")
            if u.url and not u.url.startswith("https://"):
                problems.append(f"innovation[{i}].use_cases[{j}]: url must start with https://")
            if u.id in used_ids:
                problems.append(f"innovation[{i}].use_cases[{j}]: duplicate id {u.id!r}")
            used_ids.add(u.id)
            ucs.append(u)
        item = replace(item, use_cases=tuple(ucs))
        used_ids.add(item.id)
        catalog.innovation[item.id] = item

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
    for k, st in enumerate(plan.get("steps") or []):
        loc = f"{where}.plan.steps[{k}]"
        if "interface" in st or "request" in st:
            problems.append(f"{loc}: 'interface'/'request' are no longer supported; this portal does not call "
                            "devices. Put the hand-off in the workflow's 'dispatch' block instead")
        step = Step(
            id=str(st["id"]),
            description=str(st["description"]),
            write=bool(st.get("write", True)),
            target=str(st.get("target", "{device}" if "device" in known else "")),
        )
        if any(x.id == step.id for x in steps):
            problems.append(f"{loc}: duplicate step id")
        _check_placeholders(step.description, known, problems, loc)
        _check_placeholders(step.target, known, problems, loc)
        steps.append(step)
    d = w.get("dispatch") or {}
    payload = d.get("payload")
    if payload is not None:
        if not isinstance(payload, dict):
            problems.append(f"{where}.dispatch.payload must be a mapping")
        else:
            for text in _strings(payload):
                _check_placeholders(text, known, problems, f"{where}.dispatch.payload")
    for key in (payload or {}):
        if is_secret_name(str(key)):
            problems.append(f"{where}.dispatch.payload: {key!r} looks like a secret; the backend holds secrets")
    dispatch = Dispatch(backend=str(d.get("backend", "TODO")), job=str(d.get("job", "TODO")), payload=payload)
    if not steps:
        problems.append(f"{where}: at least one plan step is required")

    if len(problems) > start:
        return None
    definition = json.dumps(w, sort_keys=True, default=str)
    return Workflow(
        id=wid, platform=platform, title=str(w["title"]), description=str(w.get("description", "")),
        risk=risk, assumption=bool(w.get("assumption", False)), params=tuple(params),
        summary=summary, steps=tuple(steps), dispatch=dispatch,
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
                errors[p.name] = "Kolom ini wajib diisi."
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
        raise ValueError("Karakter kontrol tidak diperbolehkan.")
    if len(value) > p.max_length:
        raise ValueError(f"Gunakan paling banyak {p.max_length} karakter.")
    if len(value) < p.min_length:
        raise ValueError(f"Gunakan paling sedikit {p.min_length} karakter.")
    if p.type == "string":
        if p.pattern and not re.fullmatch(p.pattern, value):
            raise ValueError(p.pattern_hint or "Nilai tidak sesuai format yang diharapkan.")
        return value
    if p.type == "int":
        if not re.fullmatch(r"-?\d{1,12}", value):
            raise ValueError("Masukkan bilangan bulat.")
        n = int(value)
        if p.min is not None and n < p.min:
            raise ValueError(f"Harus minimal {p.min}.")
        if p.max is not None and n > p.max:
            raise ValueError(f"Harus maksimal {p.max}.")
        return n
    if p.type == "enum":
        if value not in {c[0] for c in p.choices}:
            raise ValueError("Pilih salah satu opsi yang tersedia.")
        return value
    if p.type == "ip":
        try:
            addr = ipaddress.ip_address(value)
        except ValueError:
            raise ValueError("Masukkan alamat IP yang valid.") from None
        if p.ip_version and addr.version != p.ip_version:
            raise ValueError(f"Masukkan alamat IPv{p.ip_version}.")
        return str(addr)
    if p.type == "cidr":
        try:
            net = ipaddress.ip_network(value, strict=True)
        except ValueError:
            raise ValueError("Masukkan jaringan dengan notasi CIDR yang valid, mis. 192.0.2.0/24 (bit host harus nol).") from None
        if p.ip_version and net.version != p.ip_version:
            raise ValueError(f"Masukkan jaringan IPv{p.ip_version}.")
        return str(net)
    if p.type == "hostname":
        if not HOSTNAME_RE.match(value):
            raise ValueError("Masukkan hostname yang valid.")
        return value
    if p.type == "device":
        dev = inventory.get(value)
        if dev is None or dev.platform != wf.platform:
            raise ValueError("Pilih perangkat dari inventaris.")
        return value
    raise ValueError("Tipe parameter tidak didukung.")  # pragma: no cover


# ----------------------------------------------------------------------------- planning


def render(template: str, values: dict[str, Any]) -> str:
    """Substitute {name} placeholders only. No attribute access, no format specs."""
    return PLACEHOLDER_RE.sub(lambda m: str(values.get(m.group(1), "")), template)


def _render_payload(node: Any, values: dict[str, Any]) -> Any:
    if isinstance(node, str):
        m = PLACEHOLDER_RE.fullmatch(node)
        return values.get(m.group(1)) if m else render(node, values)  # a lone {x} keeps its type
    if isinstance(node, dict):
        return {k: _render_payload(v, values) for k, v in node.items()}
    if isinstance(node, list):
        return [_render_payload(v, values) for v in node]
    return node


def build_plan(wf: Workflow, values: dict[str, Any], inventory: Inventory) -> dict[str, Any]:
    """The preview: what will be requested, from your inputs alone.

    The portal never reads or changes devices, so this is not a diff against device state.
    TODO: optional "check mode" call to the automation backend for a real diff.
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
            "write": s.write,
        })
    d = wf.dispatch
    payload = _render_payload(d.payload, values) if d.payload is not None else dict(values)
    return {
        "summary": render(wf.summary, values) or wf.title,
        "steps": steps,
        "writes": sum(1 for s in steps if s["write"]),
        "dispatch": {"backend": d.backend, "job": d.job, "defined": d.defined, "payload": payload},
        "note": "Portal tidak mengubah perangkat. Setelah dikonfirmasi, permintaan ini diteruskan ke backend "
                "otomasi yang melakukan perubahan. Pratinjau ini dibuat hanya dari masukan Anda.",
    }


def plan_hash(plan: dict[str, Any], params: dict[str, Any]) -> str:
    blob = json.dumps({"plan": plan, "params": params}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def replace_dispatch(wf: Workflow, **changes: Any) -> Workflow:
    """Copy of a workflow with a different dispatch (used by tests and tooling)."""
    from dataclasses import replace
    d = wf.dispatch
    new = Dispatch(changes.get("backend", d.backend), changes.get("job", d.job), changes.get("payload", d.payload))
    return replace(wf, dispatch=new)


def load_sources(path: Path, catalog: WorkflowCatalog) -> dict[str, dict]:
    """Source text (copied as-is from a reference document) for innovation use-case cards.

    Returns {use_case_id: entry}. A missing file means no source text. Unknown ids or a malformed structure
    stop startup, like any other config error.
    """
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    known = {u.id for i in catalog.innovation.values() for u in i.use_cases}
    problems: list[str] = []
    cases = raw.get("cases") or {}
    for cid, case in cases.items():
        if cid not in known:
            problems.append(f"use_case_sources: unknown use case id {cid!r}")
            continue
        if not isinstance(case, dict) or not isinstance(case.get("blocks"), list):
            problems.append(f"use_case_sources.{cid}: 'blocks' must be a list")
            continue
        for k, b in enumerate(case["blocks"]):
            loc = f"use_case_sources.{cid}.blocks[{k}]"
            if not isinstance(b, dict) or not b.get("title"):
                problems.append(f"{loc}: needs a title")
                continue
            if b.get("kind") == "blueprint":
                need = ("problem", "solution", "trust", "readiness", "architecture", "impact", "effort", "roadmap")
                for key in need:
                    if key not in b:
                        problems.append(f"{loc}: blueprint is missing {key!r}")
            elif b.get("kind") == "flow":
                cols = len(b.get("stages") or [])
                for lane in b.get("lanes") or []:
                    for st in lane.get("steps") or []:
                        if st.get("arrow") not in (None, "up", "down"):
                            problems.append(f"{loc}: step {st.get('n')} arrow must be up or down")
                        if not (1 <= int(st.get("col", 0)) <= cols):
                            problems.append(f"{loc}: step {st.get('n')} has a column outside the stages")
                if not cols or not b.get("lanes"):
                    problems.append(f"{loc}: flow needs stages and lanes")
            else:
                problems.append(f"{loc}: kind must be 'blueprint' or 'flow'")
    if problems:
        raise WorkflowConfigError(problems)
    return {cid: dict(case, document=raw.get("document", "")) for cid, case in cases.items()}
