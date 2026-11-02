"""PowerContext stores task state; the local pointer contains citations only."""
from __future__ import annotations

import json
import os
from pathlib import Path

from powercontext.artifacts import MemoryCitation
from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig, GetMemoryEntryRequest, RememberMemoryRequest, open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft

from .repository import digest


async def task_state(directory: Path, project: str, task: str, value: dict | None = None):
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    identity = digest(json.dumps([project, task]).encode())
    pointer = directory / f"{identity}.json"
    reference = json.loads(pointer.read_text()) if pointer.exists() else None
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{directory / 'runtime.db'}"))
    async with open_builtin_runtime(config, scheduler_path=directory / "scheduler.db") as runtime:
        if reference is None:
            if value is None:
                return {"state": None, "pid": os.getpid()}
            scope = await runtime.scopes.create(ScopeDraft(
                title=f"SDD {project}: {task}", summary="Engineering task and verification state",
                idempotency_key=identity,
            ))
            reference = {"scope_id": scope.scope_id}
        memory = runtime.memory.for_scope(reference["scope_id"])
        if value is not None:
            payload = {"project_id": project, "task_id": task, **value}
            saved = await memory.remember(RememberMemoryRequest(entries=(
                MemoryEntryInput(kind="outcome", text=json.dumps(payload, ensure_ascii=False)),
            )))
            if saved.entry is not None:
                reference["citation"] = saved.entry.citation.model_dump(mode="json")
            if "citation" not in reference:
                raise RuntimeError("PowerContext returned no saved state citation")
            temporary = pointer.with_suffix(".tmp")
            temporary.write_text(json.dumps(reference), encoding="utf-8")
            temporary.replace(pointer)
        stored = await memory.get(GetMemoryEntryRequest(
            citation=MemoryCitation.model_validate(reference["citation"])))
        payload = json.loads(stored.entry.text)
        if payload["project_id"] != project or payload["task_id"] != task:
            raise ValueError("State scope does not match the task")
        return {"state": payload, "reference": reference, "pid": os.getpid()}


def reuse_state(saved: dict, fingerprints: dict[str, str]):
    """A past passing test is evidence for its recorded inputs, not future code."""
    result = dict(saved)
    value = saved.get("state")
    if value:
        result["validation_applicable"] = value.get("fingerprints") == fingerprints
        result["next_action"] = (
            "Continue from the saved completed/todo lists"
            if result["validation_applicable"] else
            "Specifications or source files changed: rebuild context and rerun tests"
        )
    return result
