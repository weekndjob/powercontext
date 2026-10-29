# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Persistent source-dependency eligibility for Memory and Topic Memory."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Boolean, Column, Integer, MetaData, String, Table, Text, insert, select, update

from powercontext.artifacts import ArtifactRef, MemoryCitation
from powercontext.builtin.runtime.models import GetMemoryEntryRequest
from powercontext.sources import SourceRef

if TYPE_CHECKING:
    from powercontext.builtin.persistence.database import AsyncDatabase
    from powercontext.builtin.runtime.application import BuiltinRuntime


class SourceLifecycleError(ValueError):
    """An invalid lifecycle registration, event, or resolution."""


class SourceLifecycleEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    revision: int = Field(strict=True, gt=0)
    sequence: int = Field(strict=True, gt=0)
    available: bool = Field(strict=True)
    reason: str

    @field_validator("node_id", "reason")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


_METADATA = MetaData()
LIFECYCLE_NODES = Table(
    "pc_source_lifecycle_nodes",
    _METADATA,
    Column("scope_id", String(255), primary_key=True),
    Column("node_id", String(255), primary_key=True),
    Column("kind", String(16), nullable=False),
    Column("reference", Text, nullable=False),
    Column("revision", Integer, nullable=True),
    Column("parents", Text, nullable=False),
    Column("policy", String(8), nullable=True),
    Column("available", Boolean, nullable=False),
    Column("sequence", Integer, nullable=False, default=0),
    Column("event", Text, nullable=True),
)


async def initialize_lifecycle(database: AsyncDatabase) -> None:
    async with database.transaction() as connection:
        await connection.run_sync(_METADATA.create_all)


class SourceLifecycleApplication:
    def __init__(self, runtime: BuiltinRuntime, database: AsyncDatabase) -> None:
        self.runtime = runtime
        self.database = database

    def for_scope(self, scope_id: str) -> ScopedSourceLifecycle:
        return ScopedSourceLifecycle(self, scope_id)

    async def unavailable_topics(self, scope_id: str) -> frozenset[str]:
        async with self.database.transaction() as connection:
            rows = (
                await connection.execute(
                    select(LIFECYCLE_NODES.c.reference).where(
                        LIFECYCLE_NODES.c.scope_id == scope_id,
                        LIFECYCLE_NODES.c.kind == "topic",
                        LIFECYCLE_NODES.c.available.is_(False),
                    )
                )
            ).scalars()
            return frozenset(ArtifactRef.model_validate_json(value).artifact_id for value in rows)


class ScopedSourceLifecycle:
    def __init__(self, application: SourceLifecycleApplication, scope_id: str) -> None:
        self.application = application
        self.scope_id = scope_id

    async def register_source(self, node_id: str, source_ref: SourceRef, *, revision: int) -> None:
        if type(revision) is not int or revision < 1:
            raise SourceLifecycleError("revision must be positive")
        try:
            await self.application.runtime.records.for_scope(self.scope_id).get_source(
                source_ref.source_type, source_ref.source_id
            )
        except Exception as exc:
            raise SourceLifecycleError("source reference is not readable") from exc
        await self._register(node_id, "source", source_ref, revision=revision)

    async def register_memory(
        self,
        node_id: str,
        citation: MemoryCitation,
        *,
        parents: tuple[str, ...],
        policy: Literal["all", "any"],
    ) -> None:
        try:
            await self.application.runtime.memory.for_scope(self.scope_id).get(GetMemoryEntryRequest(citation=citation))
        except Exception as exc:
            raise SourceLifecycleError("memory citation is not readable") from exc
        await self._register(node_id, "memory", citation, parents=parents, policy=policy)

    async def register_topic(
        self,
        node_id: str,
        artifact_ref: ArtifactRef,
        *,
        parents: tuple[str, ...],
        policy: Literal["all", "any"],
    ) -> None:
        if artifact_ref.family != "topic-memory":
            raise SourceLifecycleError("topic reference has the wrong family")
        try:
            await self.application.runtime.records.for_scope(self.scope_id).get_artifact_revision(
                artifact_ref.family, artifact_ref.artifact_id, artifact_ref.revision
            )
        except Exception as exc:
            raise SourceLifecycleError("topic reference is not readable") from exc
        await self._register(node_id, "topic", artifact_ref, parents=parents, policy=policy)

    async def _register(
        self,
        node_id: str,
        kind: str,
        reference: SourceRef | MemoryCitation | ArtifactRef,
        *,
        revision: int | None = None,
        parents: tuple[str, ...] = (),
        policy: str | None = None,
    ) -> None:
        if not isinstance(node_id, str) or not node_id.strip():
            raise SourceLifecycleError("node_id must not be blank")
        if kind != "source" and (
            not parents or len(set(parents)) != len(parents) or node_id in parents or policy not in {"all", "any"}
        ):
            raise SourceLifecycleError("invalid dependency declaration")
        serialized = reference.model_dump_json()
        async with self.application.database.transaction() as connection:
            nodes = await self._load(connection)
            existing = nodes.get(node_id)
            if existing is not None:
                if (
                    existing["kind"] != kind
                    or existing["reference"] != serialized
                    or existing["revision"] != revision
                    or tuple(json.loads(existing["parents"])) != parents
                    or existing["policy"] != policy
                ):
                    raise SourceLifecycleError("node identity conflict")
            else:
                if any(parent not in nodes for parent in parents):
                    raise SourceLifecycleError("unknown parent")
                available = True if kind == "source" else self._supported(nodes, parents, policy)
                await connection.execute(
                    insert(LIFECYCLE_NODES).values(
                        scope_id=self.scope_id,
                        node_id=node_id,
                        kind=kind,
                        reference=serialized,
                        revision=revision,
                        parents=json.dumps(parents),
                        policy=policy,
                        available=available,
                        sequence=0,
                    )
                )
        if kind == "memory":
            await self._reconcile_memory()

    async def apply(self, event: SourceLifecycleEvent) -> list[str]:
        async with self.application.database.transaction() as connection:
            nodes = await self._load(connection)
            source = nodes.get(event.node_id)
            if source is None or source["kind"] != "source" or source["revision"] != event.revision:
                raise SourceLifecycleError("unknown source or revision")
            prior_sequence = source["sequence"]
            encoded = event.model_dump_json()
            if event.sequence < prior_sequence or (event.sequence == prior_sequence and source["event"] != encoded):
                raise SourceLifecycleError("event sequence conflict")
            if event.sequence > prior_sequence:
                await connection.execute(
                    update(LIFECYCLE_NODES)
                    .where(LIFECYCLE_NODES.c.scope_id == self.scope_id, LIFECYCLE_NODES.c.node_id == event.node_id)
                    .values(available=event.available, sequence=event.sequence, event=encoded)
                )
        await self._reconcile()
        async with self.application.database.transaction() as connection:
            nodes = await self._load(connection)
        return sorted(node_id for node_id, node in nodes.items() if node["available"])

    async def resolve(self, node_id: str, *, purpose: Literal["generation", "audit"]):
        if purpose not in {"generation", "audit"}:
            raise SourceLifecycleError("unknown purpose")
        async with self.application.database.transaction() as connection:
            nodes = await self._load(connection)
        node = nodes.get(node_id)
        if node is None or (purpose == "generation" and not node["available"]):
            raise SourceLifecycleError("node unavailable")
        model = {"source": SourceRef, "memory": MemoryCitation, "topic": ArtifactRef}[node["kind"]]
        return model.model_validate_json(node["reference"])

    async def _reconcile(self) -> None:
        async with self.application.database.transaction() as connection:
            nodes = await self._load(connection)
        desired: dict[str, bool] = {}
        def eligible(node_id: str) -> bool:
            if node_id in desired:
                return desired[node_id]
            node = nodes[node_id]
            if node["kind"] == "source":
                desired[node_id] = bool(node["available"])
            else:
                parents = tuple(json.loads(node["parents"]))
                states = tuple(eligible(parent) for parent in parents)
                desired[node_id] = all(states) if node["policy"] == "all" else any(states)
            return desired[node_id]

        for node_id in nodes:
            eligible(node_id)
        await self._reconcile_memory(desired)
        async with self.application.database.transaction() as connection:
            for node_id, available in desired.items():
                if bool(nodes[node_id]["available"]) != available:
                    await connection.execute(
                        update(LIFECYCLE_NODES)
                        .where(LIFECYCLE_NODES.c.scope_id == self.scope_id, LIFECYCLE_NODES.c.node_id == node_id)
                        .values(available=available)
                    )

    async def _reconcile_memory(self, desired: dict[str, bool] | None = None) -> None:
        async with self.application.database.transaction() as connection:
            nodes = await self._load(connection)
        if desired is None:
            desired = {node_id: bool(node["available"]) for node_id, node in nodes.items()}
        runtime = self.application.runtime
        async with runtime._context(self.scope_id) as context, runtime._locked(self.scope_id):
            service = context.artifacts.memory
            for node_id, node in nodes.items():
                if node["kind"] != "memory":
                    continue
                citation = MemoryCitation.model_validate_json(node["reference"])
                current = await service.head(citation.memory_ref.artifact_id)
                entry = next((item for item in await service.entries(current) if item.entry_id == citation.entry_id), None)
                if entry is None or entry.entry_version_id != citation.entry_version_id:
                    raise SourceLifecycleError("registered memory version changed")
                state = next(item.state for item in current.content.manifest.entries if item.entry_id == entry.entry_id)
                if desired[node_id] and state != "active":
                    await service.reactivate(current, entries=(entry,), reason="source lifecycle restored")
                elif not desired[node_id] and state != "inactive":
                    await service.forget(current, entries=(entry,), reason="source lifecycle withdrawn")

    async def _load(self, connection) -> dict[str, dict]:
        rows = (
            await connection.execute(select(LIFECYCLE_NODES).where(LIFECYCLE_NODES.c.scope_id == self.scope_id))
        ).mappings()
        return {str(row["node_id"]): dict(row) for row in rows}

    @staticmethod
    def _supported(nodes: dict, parents: tuple[str, ...], policy: str | None) -> bool:
        states = [bool(nodes[parent]["available"]) if isinstance(nodes[parent], dict) else bool(nodes[parent]) for parent in parents]
        return all(states) if policy == "all" else any(states)


__all__ = ["SourceLifecycleError", "SourceLifecycleEvent", "SourceLifecycleApplication", "initialize_lifecycle"]
