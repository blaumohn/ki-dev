"""Append-only planning deltas and deterministic graph projection."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError


class PlanningError(ValueError):
    """A delta, store or source violates the planning contract."""


def digest(value: Any) -> str:
    return hashlib.sha256(encode(value)).hexdigest()


def encode(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2,
        allow_nan=False,
    ).encode("utf-8") + b"\n"


def read_json(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_keys,
            parse_constant=_invalid_constant,
        )
    except (ValueError, UnicodeError) as exc:
        raise PlanningError(f"{path}: {exc}") from exc


def resolve(
    store: Path, *, at: int | None = None,
    root: Path | None = None,
) -> dict:
    """Replay a contiguous, hash-bound history; optionally verify
    sources."""
    state: dict = {
        "step": 0, "head": None, "types": {},
        "nodes": {}, "edges": {}, "retired": [],
    }
    if at is not None and at < 0:
        raise PlanningError("at must be non-negative")
    if store.exists() and not store.is_dir():
        raise PlanningError("store must be a directory")
    paths = sorted(store.glob("*.json"))
    for index, path in enumerate(paths, 1):
        if at is not None and index > at:
            break
        if path.name != f"{index:06d}.json":
            raise PlanningError(f"non-contiguous step: {path.name}")
        state = apply_delta(state, read_json(path), root=root)
    if at is not None and state["step"] != at:
        raise PlanningError(f"step {at} does not exist")
    return state


def append(store: Path, candidate: Path, root: Path) -> dict:
    """Validate before exclusively creating the next immutable step
    file."""
    delta = read_json(candidate)
    state = apply_delta(resolve(store, root=root), delta, root=root)
    store.mkdir(parents=True, exist_ok=True)
    path = store / f"{state['step']:06d}.json"
    try:
        with path.open("xb") as stream:
            stream.write(encode(delta))
    except FileExistsError as exc:
        raise PlanningError("step exists; rebase the delta") from exc
    return state


def apply_delta(
    previous: dict, delta: dict, *, root: Path | None = None,
) -> dict:
    """Validate a complete transaction without mutating its input
    state."""
    _validate(DELTA_SCHEMA, delta)
    if delta["step"] != previous["step"] + 1:
        raise PlanningError("step must follow the current head")
    if delta["parent"] != previous["head"]:
        raise PlanningError("parent does not match the current head")
    state = json.loads(encode(previous))
    for definition in delta["types"]:
        key = definition["id"]
        if key in state["types"]:
            raise PlanningError(f"immutable type already exists: {key}")
        _check_schema(definition["schema"])
        state["types"][key] = definition
    for collection, kind in (("nodes", "node"), ("edges", "edge")):
        seen: set[str] = set()
        for operation in delta[collection]:
            key = operation["id"]
            if key in seen:
                raise PlanningError(f"duplicate operation: {key}")
            seen.add(key)
            _apply_operation(state, collection, kind, operation, root)
    for edge in state["edges"].values():
        for endpoint in ("source", "target"):
            if edge[endpoint] not in state["nodes"]:
                raise PlanningError(
                    f"dangling edge {edge['id']}: {edge[endpoint]}"
                )
    state.update(step=delta["step"], head=digest(delta))
    return state


def source_ref(root: Path, path: str, start: int, end: int) -> dict:
    source = _source_path(root, path)
    raw = source.read_bytes()
    count = len(raw.decode("utf-8").splitlines())
    if not 1 <= start <= end <= count:
        raise PlanningError(
            f"invalid line range for {path}: {start}:{end}"
        )
    return {
        "path": path, "sha256": hashlib.sha256(raw).hexdigest(),
        "start": start, "end": end,
    }


def render(state: dict) -> str:
    """A stable human-readable view; no semantic rewriting."""
    lines = [f"# Planungsstand {state['step']}", ""]
    for node in sorted(
        state["nodes"].values(), key=lambda obj: obj["id"]
    ):
        lines.extend([
            f"## {node['id']}", "",
            f"Typ: `{node['type']}` · Ort: `{node['location']}` · "
            f"Revision: `{node['revision']}`",
            "", "```json", encode(node["data"]).decode().rstrip(),
            "```", "",
        ])
        for ref in node["sources"]:
            lines.append(
                f"Quelle: {ref['path']}:{ref['start']}–{ref['end']}"
            )
        lines.append("")
    lines.extend(["## Beziehungen", ""])
    for edge in sorted(
        state["edges"].values(), key=lambda obj: obj["id"]
    ):
        lines.append(
            f"- {edge['id']}: {edge['source']} → {edge['target']} "
            f"({edge['type']}); "
            + json.dumps(
                edge["data"], ensure_ascii=False, sort_keys=True
            )
        )
    return "\n".join(lines) + "\n"


def _apply_operation(state, collection, kind, operation, root):
    key = operation["id"]
    existing = state[collection].get(key)
    revision = existing["revision"] if existing else None
    if operation["expected"] != revision:
        raise PlanningError(f"revision mismatch: {key}")
    if root is not None:
        for ref in operation["sources"]:
            actual = source_ref(
                root, ref["path"], ref["start"], ref["end"],
            )
            if actual != ref:
                raise PlanningError(f"source changed: {ref['path']}")
    if operation["op"] == "delete":
        if existing is None:
            raise PlanningError(f"cannot delete missing object: {key}")
        del state[collection][key]
        state["retired"].append(f"{collection}/{key}")
        return
    if f"{collection}/{key}" in state["retired"]:
        raise PlanningError(f"retired identity cannot be reused: {key}")
    definition = state["types"].get(operation["type"])
    if definition is None or definition["kind"] != kind:
        raise PlanningError(
            f"unknown or wrong type: {operation['type']}"
        )
    _validate(definition["schema"], operation["data"])
    has_endpoints = "source" in operation or "target" in operation
    if kind == "node" and has_endpoints:
        raise PlanningError("nodes cannot have edge endpoints")
    if kind == "edge" and not all(
        field in operation for field in ("source", "target")
    ):
        raise PlanningError("edges need source and target")
    if kind == "node" and "location" not in operation:
        raise PlanningError(f"node needs a location: {key}")
    if kind == "edge" and "location" in operation:
        raise PlanningError(f"edge cannot carry a location: {key}")
    value = {
        name: value for name, value in operation.items()
        if name not in ("op", "expected")
    }
    value["revision"] = digest(operation)
    state[collection][key] = value


def _validate(schema, value):
    try:
        Draft202012Validator(schema).validate(value)
    except ValidationError as exc:
        raise PlanningError(exc.message) from exc


def _check_schema(schema):
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise PlanningError(exc.message) from exc
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key in _REF_KEYS and not value.startswith("#"):
                raise PlanningError(
                    "only local schema references allowed"
                )
            if isinstance(value, (dict, list)):
                _check_local_refs(value)


def _check_local_refs(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _REF_KEYS and not item.startswith("#"):
                raise PlanningError(
                    "only local schema references allowed"
                )
            _check_local_refs(item)
    elif isinstance(value, list):
        for item in value:
            _check_local_refs(item)


def _source_path(root, path):
    candidate = (root / path).resolve()
    if Path(path).is_absolute() or not candidate.is_relative_to(
        root.resolve()
    ):
        raise PlanningError(f"source outside repository: {path}")
    return candidate


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PlanningError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value):
    raise PlanningError(f"non-JSON constant: {value}")


def _object(properties, required=None):
    return {
        "type": "object", "properties": properties,
        "required": list(properties) if required is None else required,
        "additionalProperties": False,
    }


_REF_KEYS = ("$ref", "$dynamicRef")
_ID = {"type": "string", "pattern": "^[a-zA-Z0-9][a-zA-Z0-9_.@/-]*$"}
_HASH = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
_NULL_HASH = {"anyOf": [_HASH, {"type": "null"}]}
_SOURCE = _object({
    "path": {"type": "string", "minLength": 1}, "sha256": _HASH,
    "start": {"type": "integer", "minimum": 1},
    "end": {"type": "integer", "minimum": 1},
})
_COMMON = {
    "id": _ID, "expected": _NULL_HASH,
    "sources": {"type": "array", "minItems": 1, "items": _SOURCE},
}
_LOCATION = {
    "type": "string", "minLength": 1,
    "pattern": "^[a-zA-Z0-9][a-zA-Z0-9_./-]*$",
}
_PUT = _object({
    **_COMMON, "op": {"const": "put"}, "type": _ID,
    "data": {"type": "object"}, "source": _ID, "target": _ID,
    "location": _LOCATION,
}, [*_COMMON, "op", "type", "data"])
_DELETE = _object({**_COMMON, "op": {"const": "delete"}})
_OPERATIONS = {"type": "array", "items": {"oneOf": [_PUT, _DELETE]}}
DELTA_SCHEMA = _object({
    "format": {"const": 1},
    "step": {"type": "integer", "minimum": 1},
    "parent": _NULL_HASH,
    "types": {"type": "array", "items": _object({
        "id": _ID, "kind": {"enum": ["node", "edge"]},
        "schema": {"type": ["object", "boolean"]},
    })},
    "nodes": _OPERATIONS, "edges": _OPERATIONS,
})
