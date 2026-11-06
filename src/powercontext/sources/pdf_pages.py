from __future__ import annotations

import hashlib
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from powercontext.artifacts.models import MemoryCitation
from powercontext.builtin.runtime.models import SearchMemoryRequest
from powercontext.sources.definitions import AdapterSourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence


class PDFDocumentInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    document_id: str
    content: bytes


class PDFPageInput(BaseModel):
    document_id: str
    document_sha256: str
    page_number: int = Field(ge=1)
    text: str


class PDFPageSource(Source):
    document_id: str
    document_sha256: str
    page_number: int
    text: str


class PDFPageProjection:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PDFPageSource
    output_class = TextEvidence

    def project(self, source: PDFPageSource) -> TextEvidence:
        return TextEvidence(
            source_type="pdf-page",
            source_id=source.name,
            content=f"{source.document_id}\n{source.text}",
            metadata={"document_id": source.document_id,
                      "document_sha256": source.document_sha256,
                      "page_number": source.page_number},
        )


class _PDFPageAdapter:
    input_class = PDFPageInput
    name = "pdf-page"
    source_class = PDFPageSource

    async def resolve(self, value: PDFPageInput) -> PDFPageSource:
        name = _source_name(value.document_id, value.document_sha256, value.page_number)
        return PDFPageSource(name=name, definition_version="1",
            materialization=SourceMaterialization.CAPTURED,
            document_id=value.document_id, document_sha256=value.document_sha256,
            page_number=value.page_number, text=value.text)

    async def read(self, source: PDFPageSource) -> PDFPageInput:
        return PDFPageInput(document_id=source.document_id,
            document_sha256=source.document_sha256, page_number=source.page_number,
            text=source.text)


PDF_PAGE_SOURCE_DEFINITION = AdapterSourceDefinition(
    adapter=_PDFPageAdapter(), version="1", projections=(PDFPageProjection(),))


def _source_name(document_id: str, digest: str, page: int) -> str:
    identity = hashlib.sha256(f"{document_id}\0{digest}\0{page}".encode()).hexdigest()
    return f"pdf-page:{identity}"


def parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    from pypdf import PdfReader
    if not value.document_id or not value.document_id.strip():
        raise ValueError("document_id must not be empty")
    digest = hashlib.sha256(value.content).hexdigest()
    try:
        reader = PdfReader(__import__("io").BytesIO(value.content), strict=True)
        if reader.is_encrypted:
            if reader.decrypt("") == 0:
                raise ValueError("encrypted PDF requires a password")
        pages = tuple(PDFPageInput(document_id=value.document_id,
            document_sha256=digest, page_number=i + 1,
            text=page.extract_text() or "") for i, page in enumerate(reader.pages))
    except Exception as error:
        if isinstance(error, ValueError) and str(error).startswith("document_id"):
            raise
        raise ValueError("invalid or unreadable PDF") from error
    if not pages:
        raise ValueError("PDF contains no pages")
    return pages






async def search_pdf_pages(memory: Any, question: str, limit: int = 10) -> tuple[MemoryCitation, ...]:
    if not question or not question.strip():
        raise ValueError("question must not be empty")
    if limit < 1:
        raise ValueError("limit must be positive")
    # Hybrid Memory search is the public scoped API; lexical terms keep the search offline.
    result = await memory.search(SearchMemoryRequest(query=question, limit=min(max(limit * 8, 20), 100), mode="fts"))
    citations = []
    seen = set()
    for hit in result.hits:
        citation = MemoryCitation(memory_ref=hit.memory_ref, entry_id=hit.entry_id,
                                  entry_version_id=hit.entry_version_id)
        key = (citation.memory_ref.model_dump_json(), citation.entry_id, citation.entry_version_id)
        if key not in seen:
            seen.add(key)
            citations.append(citation)
        if len(citations) >= limit:
            break
    return tuple(citations)
