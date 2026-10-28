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

"""Captured CSV rows with stable identities and exact textual evidence."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterator
from urllib.parse import quote

from pydantic import BaseModel, model_validator

from powercontext.sources import (
    TEXT_EVIDENCE_PROJECTION_KEY,
    AdapterSourceDefinition,
    Source,
    SourceDefinition,
    SourceMaterialization,
    TextEvidence,
)

CSV_ROW_SOURCE_NAME = "csv-row"
_MAX_SOURCE_ID_LENGTH = 256


def _validate_document_id(document_id: str) -> None:
    if not document_id or document_id != document_id.strip():
        raise ValueError("document_id must be non-empty and have no surrounding whitespace")  # noqa: TRY003


def csv_row_source_id(document_id: str, primary_key_value: str) -> str:
    """Identify a row by its document and exact primary-key value."""

    _validate_document_id(document_id)
    if not primary_key_value or not primary_key_value.strip():
        raise ValueError("primary_key_value must not be blank")  # noqa: TRY003
    identity = f"csv:{quote(document_id, safe='')}:{quote(primary_key_value, safe='')}"
    if len(identity) > _MAX_SOURCE_ID_LENGTH:
        raise ValueError("CSV row source ID exceeds 256 characters")  # noqa: TRY003
    return identity


class CSVDocumentInput(BaseModel):
    document_id: str
    primary_key: str
    content: bytes


class CSVRowInput(BaseModel):
    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]

    @model_validator(mode="after")
    def validate_row(self) -> CSVRowInput:
        csv_row_source_id(self.document_id, self.primary_key_value)
        if not self.primary_key or not self.columns or len(self.columns) != len(self.values):
            raise ValueError("CSV row must have a primary key and matching columns and values")  # noqa: TRY003
        if any(not column.strip() for column in self.columns) or len(set(self.columns)) != len(self.columns):
            raise ValueError("CSV row columns must be non-blank and unique")  # noqa: TRY003
        if self.primary_key not in self.columns:
            raise ValueError("primary_key must exactly match a CSV column")  # noqa: TRY003
        if self.values[self.columns.index(self.primary_key)] != self.primary_key_value:
            raise ValueError("primary_key_value must match the original row value")  # noqa: TRY003
        return self


class CSVRowSource(Source):
    source_id: str
    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]


def _parse_header(reader: Iterator[list[str]], primary_key: str) -> tuple[tuple[str, ...], int]:
    try:
        columns = tuple(next(reader))
    except StopIteration as error:
        raise ValueError("CSV document must contain a header") from error  # noqa: TRY003
    if not columns or any(not column.strip() for column in columns):
        raise ValueError("CSV header columns must not be blank")  # noqa: TRY003
    if len(set(columns)) != len(columns):
        raise ValueError("CSV header columns must be unique")  # noqa: TRY003
    if primary_key not in columns:
        raise ValueError("primary_key must exactly match a CSV header column")  # noqa: TRY003
    return columns, columns.index(primary_key)


def _parse_rows(
    value: CSVDocumentInput,
    reader: Iterator[list[str]],
    columns: tuple[str, ...],
    key_index: int,
) -> tuple[CSVRowInput, ...]:
    rows: list[CSVRowInput] = []
    seen_keys: set[str] = set()
    for fields in reader:
        if not fields:
            continue
        if len(fields) != len(columns):
            raise ValueError("CSV row width differs from the header")  # noqa: TRY003
        key = fields[key_index]
        if not key.strip():
            raise ValueError("CSV primary key must not be blank")  # noqa: TRY003
        if key in seen_keys:
            raise ValueError("CSV primary keys must be unique within a document")  # noqa: TRY003
        seen_keys.add(key)
        rows.append(
            CSVRowInput(
                document_id=value.document_id,
                primary_key=value.primary_key,
                primary_key_value=key,
                columns=columns,
                values=tuple(fields),
            )
        )
    return tuple(rows)


def parse_csv_document(value: CSVDocumentInput) -> tuple[CSVRowInput, ...]:
    """Parse and validate every row before exposing any result."""

    _validate_document_id(value.document_id)
    if not value.primary_key:
        raise ValueError("primary_key must be non-empty")  # noqa: TRY003
    try:
        text = value.content.decode("utf-8-sig", errors="strict")
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=",", quotechar='"', doublequote=True, strict=True)
        columns, key_index = _parse_header(reader, value.primary_key)
        return _parse_rows(value, reader, columns, key_index)
    except (UnicodeError, csv.Error) as error:
        raise ValueError("CSV document has invalid encoding or quoting") from error  # noqa: TRY003


class CSVRowSourceAdapter:
    input_class = CSVRowInput
    name = CSV_ROW_SOURCE_NAME
    source_class = CSVRowSource

    async def resolve(self, value: CSVRowInput, /) -> CSVRowSource:
        identity = csv_row_source_id(value.document_id, value.primary_key_value)
        return CSVRowSource(
            name=identity,
            source_id=identity,
            materialization=SourceMaterialization.CAPTURED,
            document_id=value.document_id,
            primary_key=value.primary_key,
            primary_key_value=value.primary_key_value,
            columns=value.columns,
            values=value.values,
        )

    async def read(self, source: CSVRowSource, /) -> CSVRowInput:
        return CSVRowInput(
            document_id=source.document_id,
            primary_key=source.primary_key,
            primary_key_value=source.primary_key_value,
            columns=source.columns,
            values=source.values,
        )


class CSVRowTextEvidenceProjection:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = CSVRowSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: CSVRowSource, /) -> TextEvidence:
        row = dict(zip(source.columns, source.values, strict=True))
        return TextEvidence(
            source_type=CSV_ROW_SOURCE_NAME,
            source_id=source.source_id,
            content=json.dumps(row, ensure_ascii=False, separators=(",", ":")),
            metadata={
                "document_id": source.document_id,
                "primary_key": source.primary_key,
                "primary_key_value": source.primary_key_value,
                "columns": list(source.columns),
                "row": row,
            },
        )


CSV_ROW_SOURCE_DEFINITION: SourceDefinition[CSVRowInput, CSVRowSource, CSVRowInput] = AdapterSourceDefinition(
    CSVRowSourceAdapter(),
    projections=(CSVRowTextEvidenceProjection(),),
)

__all__ = [
    "CSV_ROW_SOURCE_DEFINITION",
    "CSVDocumentInput",
    "CSVRowInput",
    "CSVRowSource",
    "csv_row_source_id",
    "parse_csv_document",
]
