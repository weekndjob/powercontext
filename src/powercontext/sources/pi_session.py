"""Capture the visible, immutable events on a selected Pi session branch."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from powercontext.sources import (
    TEXT_EVIDENCE_PROJECTION_KEY,
    AdapterSourceDefinition,
    ConnectorRunCompletion,
    ConnectorRunSession,
    ConnectorRunStatus,
    Source,
    SourceDefinition,
    SourceMaterialization,
    TextEvidence,
)


class PiSessionInput(BaseModel):
    content: bytes
    leaf_id: str | None = None


class PiEventInput(BaseModel):
    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, Any]


class PiEventSource(Source):
    source_id: str
    event: PiEventInput


def _identity(session_id: str, event_id: str) -> str:
    payload = json.dumps([session_id, event_id], ensure_ascii=False, separators=(",", ":"))
    return "pi:" + hashlib.sha256(payload.encode()).hexdigest()


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"invalid JSON value: {value}")


def _parse_records(content: bytes) -> tuple[str, dict[str, dict[str, Any]], str | None]:
    try:
        lines = [
            json.loads(line, parse_constant=_reject_nonfinite)
            for line in content.decode("utf-8-sig").splitlines()
            if line.strip()
        ]
    except (UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError("invalid Pi JSONL") from error
    if not lines or not isinstance(lines[0], dict):
        raise ValueError("missing Pi session header")
    header = lines[0]
    session_id = header.get("id")
    if (header.get("type") != "session" or type(header.get("version")) is not int
            or header["version"] != 3 or not isinstance(session_id, str) or not session_id.strip()):
        raise ValueError("invalid Pi session header")
    records: dict[str, dict[str, Any]] = {}
    last: str | None = None
    for record in lines[1:]:
        if not isinstance(record, dict):
            raise ValueError("invalid Pi event")
        event_id, parent = record.get("id"), record.get("parentId")
        if not isinstance(event_id, str) or not event_id.strip() or event_id in records:
            raise ValueError("duplicate or invalid Pi event ID")
        if "parentId" not in record or not isinstance(record.get("type"), str) or not record["type"]:
            raise ValueError("Pi event must declare type and parentId")
        if parent is not None and (not isinstance(parent, str) or parent not in records):
            raise ValueError("Pi parent must precede its child")
        records[event_id] = record
        last = event_id
    return session_id, records, last


def _visible_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for block in value:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text" and isinstance(block.get("text"), str):
            parts.append(block["text"])
        elif kind == "toolCall":
            name, call_id = block.get("name", ""), block.get("id", "")
            arguments = json.dumps(block.get("arguments", {}), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            parts.append(f"[tool_call {name} {call_id}] {arguments}")
    return "\n".join(parts)


def _event_content(record: dict[str, Any]) -> tuple[str, str] | None:
    kind = record.get("type")
    if kind in {"compaction", "branch_summary"}:
        role, body = kind, record.get("summary")
    elif kind == "custom_message":
        role, body = "custom", _visible_text(record.get("content"))
    elif kind == "message" and isinstance(record.get("message"), dict):
        message = record["message"]
        role = message.get("role")
        if role == "toolResult":
            result = _visible_text(message.get("content"))
            if not result.strip():
                return None
            body = f"[tool_result {message.get('toolName', '')} {message.get('toolCallId', '')}] {result}"
        elif role == "bashExecution":
            command, output = message.get("command", ""), message.get("output", "")
            if not isinstance(command, str) or not isinstance(output, str) or not (command.strip() or output.strip()):
                return None
            body = f"$ {command}\n{output}"
        else:
            body = _visible_text(message.get("content"))
    else:
        return None
    if not isinstance(role, str) or not isinstance(body, str) or not body.strip():
        return None
    return role, f"{role}: {body}"


def parse_pi_session(value: PiSessionInput) -> tuple[PiEventInput, ...]:
    """Validate the entire graph, then expose visible ancestors of the chosen leaf."""
    session_id, records, last = _parse_records(value.content)
    leaf = value.leaf_id if value.leaf_id is not None else last
    if leaf is None:
        raise ValueError("Pi session has no leaf")
    if leaf not in records:
        raise ValueError("Pi leaf does not exist")
    path: list[dict[str, Any]] = []
    seen: set[str] = set()
    while leaf is not None:
        if leaf in seen:
            raise ValueError("Pi graph has a cycle")
        seen.add(leaf)
        record = records[leaf]
        path.append(record)
        leaf = record.get("parentId")
    result: list[PiEventInput] = []
    for record in reversed(path):
        visible = _event_content(record)
        if visible is None:
            continue
        role, content = visible
        result.append(PiEventInput(session_id=session_id, event_id=record["id"], parent_id=record.get("parentId"),
                                   event_type=record["type"], role=role, content=content, record=record))
    return tuple(result)


class PiEventSourceAdapter:
    input_class = PiEventInput
    name = "pi-event"
    source_class = PiEventSource

    async def resolve(self, value: PiEventInput, /) -> PiEventSource:
        identity = _identity(value.session_id, value.event_id)
        return PiEventSource(name=identity, source_id=identity, materialization=SourceMaterialization.CAPTURED,
                             event=value)

    async def read(self, source: PiEventSource, /) -> PiEventInput:
        return source.event


class PiEventTextEvidenceProjection:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PiEventSource
    output_class = TextEvidence

    def project(self, source: PiEventSource, /) -> TextEvidence:
        event = source.event
        return TextEvidence(source_type="pi-event", source_id=source.source_id, content=event.content,
                            metadata={"session_id": event.session_id, "event_id": event.event_id,
                                      "parent_id": event.parent_id, "event_type": event.event_type, "role": event.role})


PI_EVENT_SOURCE_DEFINITION: SourceDefinition[PiEventInput, PiEventSource, PiEventInput] = AdapterSourceDefinition(
    PiEventSourceAdapter(), projections=(PiEventTextEvidenceProjection(),)
)


class PiSessionConnector:
    name = "pi-session-history"
    version = "1"
    source_definitions = frozenset({"pi-event"})

    def __init__(self, path: str | Path, leaf_id: str | None = None) -> None:
        self.path = Path(path)
        self.leaf_id = leaf_id

    async def run(self, session: ConnectorRunSession, /) -> ConnectorRunCompletion:
        raw = self.path.read_bytes()
        session_id, records, _ = _parse_records(raw)
        events = parse_pi_session(PiSessionInput(content=raw, leaf_id=self.leaf_id))
        previous = session.checkpoint
        if previous is None:
            known: dict[str, str] = {}
        elif isinstance(previous, dict) and previous.get("session_id") == session_id and isinstance(previous.get("events"), dict):
            known = dict(previous["events"])
        else:
            raise ValueError("Pi checkpoint does not match session")
        for event_id, digest in known.items():
            record = records.get(event_id)
            if record is None or _record_digest(record) != digest:
                raise ValueError("previously imported Pi event changed")
        updated = dict(known)
        for event in events:
            if event.event_id in updated:
                continue
            await session.submit(_identity(session_id, event.event_id), "pi-event", event)
            updated[event.event_id] = _record_digest(event.record)
        return ConnectorRunCompletion(status=ConnectorRunStatus.COMPLETE, checkpoint={"session_id": session_id, "events": updated})


def _record_digest(record: dict[str, Any]) -> str:
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


__all__ = ["PiSessionInput", "PiEventInput", "PiEventSource", "parse_pi_session", "PI_EVENT_SOURCE_DEFINITION", "PiSessionConnector"]
