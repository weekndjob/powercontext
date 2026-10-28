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

"""HTTP scoring adapter for globally ranked Memory search candidates."""

from __future__ import annotations

import math
from typing import Any

import httpx

from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.artifacts.memory.reranking import MemoryRerankDecision
from powercontext.builtin.inference import InferenceUsage


def _batch_scores(payload: Any, expected_ranks: set[int]) -> dict[int, int | float]:
    if type(payload) is not dict or set(payload) != {"scores"} or type(payload["scores"]) is not list:
        raise ValueError("HTTP reranker response must contain only a scores list")  # noqa: TRY003

    scores: dict[int, int | float] = {}
    for item in payload["scores"]:
        if type(item) is not dict or set(item) != {"rank", "score"}:
            raise ValueError("HTTP reranker score must contain only rank and score")  # noqa: TRY003
        rank, score = item["rank"], item["score"]
        if type(rank) is not int or rank not in expected_ranks or rank in scores:
            raise ValueError("HTTP reranker ranks must cover the current batch exactly once")  # noqa: TRY003
        if type(score) not in (int, float) or (type(score) is float and not math.isfinite(score)):
            raise ValueError("HTTP reranker score must be a finite number")  # noqa: TRY003
        scores[rank] = score

    if set(scores) != expected_ranks:
        raise ValueError("HTTP reranker ranks must cover the current batch exactly once")  # noqa: TRY003
    return scores


class HTTPMemoryReranker:
    """Score every candidate in bounded HTTP batches, then rank the full pool."""

    def __init__(
        self,
        endpoint: str,
        *,
        client: httpx.AsyncClient,
        batch_size: int = 32,
        policy_id: str = "http-cross-encoder-v1",
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")  # noqa: TRY003
        self.endpoint = endpoint
        self.client = client
        self.batch_size = batch_size
        self.policy_id = policy_id

    async def rerank(
        self,
        query: str,
        candidates: tuple[MemoryHit, ...],
        limit: int,
        /,
    ) -> MemoryRerankDecision:
        if not candidates or not 1 <= limit <= len(candidates):
            raise ValueError("rerank needs candidates and a limit within their count")  # noqa: TRY003

        scores: dict[int, int | float] = {}
        request_count = 0
        for start in range(0, len(candidates), self.batch_size):
            batch = candidates[start : start + self.batch_size]
            request_items = [
                {"rank": start + offset + 1, "text": candidate.text} for offset, candidate in enumerate(batch)
            ]
            response = await self.client.post(self.endpoint, json={"query": query, "candidates": request_items})
            request_count += 1
            response.raise_for_status()
            scores.update(_batch_scores(response.json(), {item["rank"] for item in request_items}))

        selected_ranks = tuple(sorted(scores, key=lambda rank: (-scores[rank], rank))[:limit])
        return MemoryRerankDecision(
            selected_ranks=selected_ranks,
            usage=InferenceUsage(requests=request_count),
        )


__all__ = ["HTTPMemoryReranker"]
