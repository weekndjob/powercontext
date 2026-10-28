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

"""Self-contained UTF-8 context packs and prefix-reuse deltas."""

# Protocol validation needs a distinct explanation at each rejected field.
# ruff: noqa: TRY003

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

_PACK_SCHEMA = "powercontext.context-pack.v1"
_DELTA_SCHEMA = "powercontext.context-pack-delta.v1"
_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")


class ContextPackError(ValueError):
    """The context pack wire data or a delta is invalid."""


def _wire(data: dict[str, object]) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContextPackError("duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ContextPackError(f"invalid JSON constant: {value}")


def _load(data: bytes) -> dict[str, Any]:
    if type(data) is not bytes:
        raise ContextPackError("wire data must be bytes")
    try:
        payload = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_pairs, parse_constant=_invalid_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContextPackError("invalid JSON wire data") from error
    if type(payload) is not dict:
        raise ContextPackError("wire payload must be a JSON object")
    return payload


def _valid_digest(value: object) -> bool:
    return type(value) is str and _DIGEST_PATTERN.fullmatch(value) is not None


def _encode_items(items: tuple[bytes, ...]) -> list[str]:
    return [base64.b64encode(item).decode("ascii") for item in items]


def _decode_items(value: object) -> tuple[bytes, ...]:
    if type(value) is not list:
        raise ContextPackError("items must be an array")
    items: list[bytes] = []
    for encoded in value:
        if type(encoded) is not str:
            raise ContextPackError("each item must be Base64 text")
        try:
            item = base64.b64decode(encoded, validate=True)
            item.decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError) as error:
            raise ContextPackError("invalid Base64 or UTF-8 item") from error
        if base64.b64encode(item).decode("ascii") != encoded:
            raise ContextPackError("noncanonical Base64 item")
        items.append(item)
    return tuple(items)


@dataclass(frozen=True)
class ContextPack:
    """A complete sequence of UTF-8 chunks with an integrity digest."""

    items: tuple[bytes, ...]
    digest: str
    byte_count: int

    @classmethod
    def build(cls, items: tuple[bytes, ...]) -> ContextPack:
        if type(items) is not tuple or any(type(item) is not bytes for item in items):
            raise ContextPackError("items must be a tuple of bytes")
        for item in items:
            try:
                item.decode("utf-8")
            except UnicodeDecodeError as error:
                raise ContextPackError("each item must be valid UTF-8") from error
        unsigned: dict[str, object] = {"schema": _PACK_SCHEMA, "items": _encode_items(items)}
        digest = "sha256:" + hashlib.sha256(_wire(unsigned)).hexdigest()
        payload = {**unsigned, "digest": digest, "byte_count": 0}
        while True:
            count = len(_wire(payload))
            if count == payload["byte_count"]:
                return cls(items=items, digest=digest, byte_count=count)
            payload["byte_count"] = count

    @classmethod
    def from_content(cls, content: str, *, chunk_bytes: int = 512) -> ContextPack:
        if type(content) is not str or type(chunk_bytes) is not int or chunk_bytes <= 0:
            raise ContextPackError("content must be text and chunk_bytes a positive integer")
        chunks: list[bytes] = []
        try:
            for line in content.splitlines(keepends=True):
                current = bytearray()
                for character in line:
                    encoded = character.encode("utf-8")
                    if len(encoded) > chunk_bytes:
                        raise ContextPackError("chunk limit cannot hold a UTF-8 character")
                    if len(current) + len(encoded) > chunk_bytes:
                        chunks.append(bytes(current))
                        current.clear()
                    current.extend(encoded)
                if current:
                    chunks.append(bytes(current))
        except UnicodeEncodeError as error:
            raise ContextPackError("content is not valid UTF-8 text") from error
        return cls.build(tuple(chunks))

    def to_bytes(self) -> bytes:
        return _wire({
            "schema": _PACK_SCHEMA,
            "items": _encode_items(self.items),
            "digest": self.digest,
            "byte_count": self.byte_count,
        })

    @classmethod
    def from_bytes(cls, data: bytes) -> ContextPack:
        payload = _load(data)
        if set(payload) != {"schema", "items", "digest", "byte_count"} or payload["schema"] != _PACK_SCHEMA:
            raise ContextPackError("invalid pack fields or schema")
        if not _valid_digest(payload["digest"]) or type(payload["byte_count"]) is not int:
            raise ContextPackError("invalid pack digest or byte_count")
        pack = cls.build(_decode_items(payload["items"]))
        if payload["digest"] != pack.digest or payload["byte_count"] != pack.byte_count:
            raise ContextPackError("pack integrity check failed")
        return pack


@dataclass(frozen=True)
class ContextPackDelta:
    """A target pack represented by retained base chunks and a new suffix."""

    base_digest: str
    target_digest: str
    prefix_items: int
    appended: tuple[bytes, ...]

    @classmethod
    def between(cls, base: ContextPack, target: ContextPack) -> ContextPackDelta:
        prefix = 0
        for base_item, target_item in zip(base.items, target.items, strict=False):
            if base_item != target_item:
                break
            prefix += 1
        return cls(base.digest, target.digest, prefix, target.items[prefix:])

    @property
    def byte_count(self) -> int:
        return len(self.to_bytes())

    def to_bytes(self) -> bytes:
        return _wire({
            "schema": _DELTA_SCHEMA,
            "base_digest": self.base_digest,
            "target_digest": self.target_digest,
            "prefix_items": self.prefix_items,
            "appended": _encode_items(self.appended),
        })

    @classmethod
    def from_bytes(cls, data: bytes) -> ContextPackDelta:
        payload = _load(data)
        if set(payload) != {"schema", "base_digest", "target_digest", "prefix_items", "appended"}:
            raise ContextPackError("invalid delta fields")
        if payload["schema"] != _DELTA_SCHEMA:
            raise ContextPackError("invalid delta schema")
        if not _valid_digest(payload["base_digest"]) or not _valid_digest(payload["target_digest"]):
            raise ContextPackError("invalid delta digest")
        prefix = payload["prefix_items"]
        if type(prefix) is not int or prefix < 0:
            raise ContextPackError("prefix_items must be a nonnegative integer")
        return cls(payload["base_digest"], payload["target_digest"], prefix, _decode_items(payload["appended"]))


def apply_context_pack_delta(base: ContextPack, delta: ContextPackDelta) -> ContextPack:
    """Rebuild a target pack using only a validated base and transmitted delta."""

    if ContextPack.from_bytes(base.to_bytes()) != base:
        raise ContextPackError("invalid base pack")
    if ContextPackDelta.from_bytes(delta.to_bytes()) != delta:
        raise ContextPackError("invalid delta")
    if delta.base_digest != base.digest or delta.prefix_items > len(base.items):
        raise ContextPackError("delta does not match the base pack")
    target = ContextPack.build((*base.items[: delta.prefix_items], *delta.appended))
    if target.digest != delta.target_digest:
        raise ContextPackError("target digest mismatch")
    return target


__all__ = ["ContextPack", "ContextPackDelta", "ContextPackError", "apply_context_pack_delta"]
