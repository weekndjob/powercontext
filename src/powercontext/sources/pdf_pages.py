"""Complete physical-page PDF evidence and scoped Memory retrieval."""

from __future__ import annotations

import hashlib
import io
import json
import re
from collections import defaultdict

from pydantic import BaseModel, Field, field_validator
from pypdf import PdfReader

from powercontext.artifacts import MemoryCitation
from powercontext.sources import (
    TEXT_EVIDENCE_PROJECTION_KEY,
    AdapterSourceDefinition,
    Source,
    SourceDefinition,
    SourceMaterialization,
    TextEvidence,
)


class PDFDocumentInput(BaseModel):
    document_id: str
    content: bytes


class PDFPageInput(BaseModel):
    document_id: str
    document_sha256: str
    page_number: int = Field(ge=1)
    text: str

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("document_id must not be blank")
        return value


class PDFPageSource(Source):
    source_id: str
    page: PDFPageInput


def _page_identity(page: PDFPageInput) -> str:
    encoded = json.dumps(
        [page.document_id, page.document_sha256, page.page_number], ensure_ascii=False, separators=(",", ":")
    )
    return "pdf:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    """Parse every physical page before returning any page result."""
    if not value.document_id.strip() or not value.content.startswith(b"%PDF-"):
        raise ValueError("invalid PDF document")
    digest = hashlib.sha256(value.content).hexdigest()
    try:
        reader = PdfReader(io.BytesIO(value.content), strict=True)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("PDF requires a password")
        pages = tuple(
            PDFPageInput(
                document_id=value.document_id,
                document_sha256=digest,
                page_number=number,
                text=page.extract_text() or "",
            )
            for number, page in enumerate(reader.pages, start=1)
        )
        if not pages:
            raise ValueError("PDF has no pages")
    except Exception as error:
        raise ValueError("PDF could not be fully parsed") from error
    return pages


class PDFPageSourceAdapter:
    input_class = PDFPageInput
    name = "pdf-page"
    source_class = PDFPageSource

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        identity = _page_identity(value)
        return PDFPageSource(name=identity, source_id=identity, materialization=SourceMaterialization.CAPTURED, page=value)

    async def read(self, source: PDFPageSource, /) -> PDFPageInput:
        return source.page


class PDFPageTextEvidenceProjection:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PDFPageSource
    output_class = TextEvidence

    def project(self, source: PDFPageSource, /) -> TextEvidence:
        page = source.page
        return TextEvidence(
            source_type="pdf-page",
            source_id=source.source_id,
            content=f"{page.document_id}\n{page.text}",
            metadata={
                "document_id": page.document_id,
                "document_sha256": page.document_sha256,
                "page_number": page.page_number,
            },
        )


PDF_PAGE_SOURCE_DEFINITION: SourceDefinition[PDFPageInput, PDFPageSource, PDFPageInput] = AdapterSourceDefinition(
    PDFPageSourceAdapter(), projections=(PDFPageTextEvidenceProjection(),)
)


_QUESTION_WORDS = frozenset(
    "a an and are as at be by can could did do does for from has have how if in into is it its of on or our per "
    "that the their there these this to was were what when where which who why will with would year years fiscal "
    "company companies financial report reported according based using use calculate answer question shown statement "
    "fy fy2020 fy2021 fy2022 fy2023".split()
)
_FINANCIAL_EXPANSIONS = (
    (("income statement", "p&l", "profit and loss"), "consolidated statement of income"),
    (("cash flow", "cash flows"), "consolidated statement of cash flows"),
    (("legal battle", "legal proceedings", "litigation"), "legal proceedings"),
    (("restructuring",), "restructuring charges"),
    (("capex", "capital expenditure"), "capital expenditures"),
    (("geograph", "geographi"), "geographic areas"),
)


def _search_queries(question: str) -> tuple[str, ...]:
    terms = [
        term for term in re.findall(r"[a-z]+|\d+", question.casefold())
        if len(term) > 2 and term not in _QUESTION_WORDS and not (term.isdigit() and len(term) == 4)
    ]
    lowered = question.casefold()
    queries = [question]
    queries.extend(expanded for triggers, expanded in _FINANCIAL_EXPANSIONS if any(trigger in lowered for trigger in triggers))
    queries.extend(" ".join(terms[index : index + 3]) for index in range(len(terms) - 2))
    queries.extend(" ".join(terms[index : index + 2]) for index in range(len(terms) - 1))
    return tuple(dict.fromkeys(queries))


async def search_pdf_pages(memory, question: str, limit: int = 10) -> tuple[MemoryCitation, ...]:
    """Fuse several lexical views of a question, preserving real Memory citations."""
    from powercontext.builtin.runtime import SearchMemoryRequest

    if limit < 1:
        return ()
    scores: dict[tuple[str, str, int, str, str], float] = defaultdict(float)
    citations: dict[tuple[str, str, int, str, str], MemoryCitation] = {}
    focus_groups: list[list[tuple[str, str, int, str, str]]] = []
    focused_queries = {expanded for _, expanded in _FINANCIAL_EXPANSIONS}
    for query_index, query in enumerate(_search_queries(question)):
        page = await memory.search(SearchMemoryRequest(query=query, mode="fts", limit=max(limit * 2, 30)))
        weight = 1.0 if query_index == 0 else 2.5 if query.startswith("consolidated statement") else 1.5 if len(query.split()) == 3 else 1.0
        focus: list[tuple[str, str, int, str, str]] = []
        for rank, hit in enumerate(page.hits):
            citation = MemoryCitation(memory_ref=hit.memory_ref, entry_id=hit.entry_id,
                                      entry_version_id=hit.entry_version_id)
            identity = (hit.memory_ref.family, hit.memory_ref.artifact_id, hit.memory_ref.revision,
                        hit.entry_id, hit.entry_version_id)
            citations[identity] = citation
            scores[identity] += weight / (rank + 8)
            focus.append(identity)
        if query in focused_queries:
            focus_groups.append(focus)
    ranked = sorted(scores, key=lambda identity: (-scores[identity], identity))
    selected: list[tuple[str, str, int, str, str]] = []
    for group in focus_groups:
        for identity in group[: max(3, min(6, limit // 3))]:
            if identity not in selected and len(selected) < limit:
                selected.append(identity)
    selected.extend(identity for identity in ranked if identity not in selected and len(selected) < limit)
    return tuple(citations[identity] for identity in selected)


__all__ = ["PDFDocumentInput", "PDFPageInput", "PDFPageSource", "parse_pdf_document", "PDF_PAGE_SOURCE_DEFINITION", "search_pdf_pages"]
