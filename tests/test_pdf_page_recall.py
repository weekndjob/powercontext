"""Regression coverage for page recall across similarly worded reports."""

from pathlib import Path

import pytest

from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import BuiltinConfig, open_builtin_contexts
from powercontext.sources.pdf_pages import search_pdf_pages


@pytest.mark.asyncio
async def test_retrieval_finds_company_report_with_plural_financial_term(tmp_path: Path) -> None:
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}"))
    async with open_builtin_contexts(config) as contexts:
        memory = (await contexts.get("reports")).artifacts.memory
        entries = [
            MemoryEntryInput(
                kind="source-evidence",
                text=f"ZEPHYR_2022_10K\nOverview page {index}. Operations across markets.",
            )
            for index in range(90)
        ]
        entries.extend(
            MemoryEntryInput(
                kind="source-evidence",
                text=f"OTHER{index}_2022_10K\nConsolidated statement of income. Revenues and expenses.",
            )
            for index in range(90)
        )
        target = "ZEPHYR_2022_10K\nConsolidated statement of income. Net revenues for the fiscal period."
        entries.append(MemoryEntryInput(kind="source-evidence", text=target))
        head = await memory.remember(memory=None, entries=tuple(entries), mode="append")
        assert head is not None
        stored = {entry.entry_id: entry.text for entry in await memory.entries(head)}

        class ScopedMemory:
            async def search(self, request):
                return await memory.search(request.query, memories=(head,), mode=request.mode, limit=request.limit)

        citations = await search_pdf_pages(ScopedMemory(), "What did Zephyr report as its fiscal year revenue?", limit=20)
        assert target in [stored[citation.entry_id] for citation in citations]
