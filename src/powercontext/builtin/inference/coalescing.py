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

"""Share concurrent embedding work and retain successful vectors in an LRU cache."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass

from powercontext.builtin.inference.models import EmbeddingResult, EmbeddingVector, InferenceUsage
from powercontext.builtin.inference.protocols import EmbeddingModel


@dataclass(frozen=True, slots=True)
class _Computed:
    vector: EmbeddingVector
    usage: InferenceUsage
    batch: object


class CoalescingEmbeddingModel:
    """Deduplicate texts across callers, including callers arriving during a request."""

    def __init__(
        self,
        model: EmbeddingModel,
        *,
        max_batch_size: int = 64,
        coalesce_ms: float = 5.0,
        cache_size: int = 1024,
    ) -> None:
        if max_batch_size < 1:
            raise ValueError("max_batch_size must be positive")
        if coalesce_ms < 0:
            raise ValueError("coalesce_ms must be nonnegative")
        if cache_size < 0:
            raise ValueError("cache_size must be nonnegative")
        self._model = model
        self.profile = model.profile
        self._max_batch_size = max_batch_size
        self._coalesce_seconds = coalesce_ms / 1000
        self._cache_size = cache_size
        self._cache: OrderedDict[str, EmbeddingVector] = OrderedDict()
        self._inflight: dict[str, asyncio.Future[_Computed]] = {}
        self._pending: list[str] = []
        self._flush_task: asyncio.Task[None] | None = None
        self._batch_tasks: set[asyncio.Task[None]] = set()

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult(vectors=(), usage=InferenceUsage(requests=0))

        loop = asyncio.get_running_loop()
        values: dict[str, EmbeddingVector | asyncio.Future[_Computed]] = {}
        for text in texts:
            if text in values:
                continue
            if text in self._cache:
                self._cache.move_to_end(text)
                values[text] = self._cache[text]
                continue
            future = self._inflight.get(text)
            if future is None:
                future = loop.create_future()
                # A caller may be cancelled after dispatch; consume an otherwise
                # unobserved provider exception without cancelling shared work.
                future.add_done_callback(self._consume_exception)
                self._inflight[text] = future
                self._pending.append(text)
            values[text] = future

        if self._pending and self._flush_task is None:
            self._flush_task = asyncio.create_task(self._flush_after_window())

        waiting = {text: value for text, value in values.items() if isinstance(value, asyncio.Future)}
        completed: dict[str, _Computed] = {}
        if waiting:
            results = await asyncio.gather(*(asyncio.shield(value) for value in waiting.values()))
            completed = dict(zip(waiting, results, strict=True))

        vectors = tuple(
            completed[text].vector if text in completed else values[text]
            for text in texts
        )
        batches: dict[object, InferenceUsage] = {}
        for value in completed.values():
            batches[value.batch] = value.usage
        usages = tuple(batches.values())
        return EmbeddingResult(
            vectors=vectors,
            usage=InferenceUsage(
                requests=sum(usage.requests for usage in usages),
                input_tokens=self._sum_optional(tuple(usage.input_tokens for usage in usages)),
                output_tokens=self._sum_optional(tuple(usage.output_tokens for usage in usages)),
            ),
        )

    async def _flush_after_window(self) -> None:
        await asyncio.sleep(self._coalesce_seconds)
        pending, self._pending = self._pending, []
        self._flush_task = None
        for start in range(0, len(pending), self._max_batch_size):
            task = asyncio.create_task(self._run_batch(tuple(pending[start : start + self._max_batch_size])))
            self._batch_tasks.add(task)
            task.add_done_callback(self._batch_tasks.discard)

    async def _run_batch(self, texts: tuple[str, ...]) -> None:
        try:
            result = await self._model.embed(texts)
            if len(result.vectors) != len(texts):
                raise ValueError("embedding vector count does not match text count")
        except BaseException as exc:
            for text in texts:
                future = self._inflight.pop(text)
                if not future.done():
                    future.set_exception(exc)
            return

        batch = object()
        for text, vector in zip(texts, result.vectors, strict=True):
            if self._cache_size:
                self._cache[text] = vector
                self._cache.move_to_end(text)
                if len(self._cache) > self._cache_size:
                    self._cache.popitem(last=False)
            future = self._inflight.pop(text)
            if not future.done():
                future.set_result(_Computed(vector, result.usage, batch))

    @staticmethod
    def _sum_optional(values: tuple[int | None, ...]) -> int | None:
        return sum(value for value in values if value is not None) if any(value is not None for value in values) else None

    @staticmethod
    def _consume_exception(future: asyncio.Future[_Computed]) -> None:
        if not future.cancelled():
            future.exception()


__all__ = ["CoalescingEmbeddingModel"]
