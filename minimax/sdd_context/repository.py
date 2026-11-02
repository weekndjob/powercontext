"""Authoritative engineering documents and real seekdb full-text retrieval."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pymysql


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def project_fingerprints(project: str, documents: list[dict]) -> dict[str, str]:
    values = {doc["path"]: doc["sha256"] for doc in documents}
    metadata = sorted((doc["path"], doc["kind"], doc["status"]) for doc in documents)
    values["@manifest"] = digest(json.dumps([project, metadata], ensure_ascii=False).encode())
    return values


def source_path(root: Path, relative: str) -> Path:
    if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError("Source path must stay within the project")
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()) or not target.is_file():
        raise ValueError(f"Missing or escaping source: {relative}")
    return target


def load_documents(root: Path) -> tuple[str, list[dict]]:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    project = manifest["project_id"]
    if not isinstance(project, str) or not project or len(project) > 64:
        raise ValueError("Invalid project ID")
    documents, seen = [], set()
    for entry in manifest["documents"]:
        relative = entry["path"]
        if relative in seen or len(relative) > 240:
            raise ValueError("Duplicate or oversized path")
        seen.add(relative)
        if entry["kind"] not in {"spec", "decision", "code", "test"}:
            raise ValueError("Unknown document kind")
        if entry["status"] not in {"active", "superseded"}:
            raise ValueError("Unknown document status")
        raw = source_path(root, relative).read_bytes()
        if not raw or len(raw) > 16000:
            raise ValueError("Documents must contain 1..16000 UTF-8 bytes")
        documents.append({**entry, "sha256": digest(raw), "body": raw.decode("utf-8")})
    if not documents:
        raise ValueError("An empty manifest cannot replace an engineering project")
    return project, documents


class EngineeringRepository:
    def __init__(self, audit: Path | None = None):
        database = os.environ.get("SEEKDB_DATABASE", "minimax_sdd")
        if not database.replace("_", "").isalnum():
            raise ValueError("Database must contain letters, digits or underscores")
        self.audit = audit
        self.connection = pymysql.connect(
            host=os.environ.get("SEEKDB_HOST", "127.0.0.1"),
            port=int(os.environ.get("SEEKDB_PORT", "2881")),
            user=os.environ.get("SEEKDB_USER", "root"),
            password=os.environ.get("SEEKDB_PASSWORD", ""),
            database=database, charset="utf8mb4", autocommit=False,
            cursorclass=pymysql.cursors.DictCursor, connect_timeout=10,
        )

    def close(self):
        self.connection.close()

    def execute(self, sql: str, params=()):
        with self.connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = list(cursor.fetchall()) if cursor.description else []
        if self.audit:
            self.audit.parent.mkdir(parents=True, exist_ok=True)
            with self.audit.open("a", encoding="utf-8") as log:
                log.write(json.dumps({"sql": sql, "params": params, "rows": rows},
                                     ensure_ascii=False, default=str) + "\n")
        return rows

    def initialize(self):
        self.execute("SELECT VERSION() AS database_version")
        self.execute("""CREATE TABLE IF NOT EXISTS sdd_documents (
            project_id VARCHAR(64) NOT NULL,
            path VARCHAR(240) NOT NULL,
            kind VARCHAR(16) NOT NULL,
            status VARCHAR(16) NOT NULL,
            sha256 CHAR(64) NOT NULL,
            body TEXT NOT NULL,
            PRIMARY KEY(project_id, path),
            FULLTEXT INDEX content_index(body) WITH PARSER space
        )""")
        self.connection.commit()

    def import_project(self, root: Path):
        project, documents = load_documents(root)
        # A manifest is a complete snapshot. Removed files cannot remain active.
        # Validate every file before touching the previous committed snapshot.
        try:
            self.execute("DELETE FROM sdd_documents WHERE project_id=%s", (project,))
            for doc in documents:
                self.execute("""INSERT INTO sdd_documents
                    (project_id,path,kind,status,sha256,body) VALUES (%s,%s,%s,%s,%s,%s)""",
                    (project, doc["path"], doc["kind"], doc["status"], doc["sha256"], doc["body"]))
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return {"project_id": project, "imported": len(documents),
                "fingerprints": project_fingerprints(project, documents)}

    def context(self, root: Path, query: str):
        if not isinstance(query, str) or not query.strip() or len(query) > 2000:
            raise ValueError("A nonempty task query of at most 2000 characters is required")
        project, documents = load_documents(root)
        # Search relevance comes from the database. Status filtering prevents
        # historical decisions from being treated as current instructions.
        rows = self.execute("""SELECT path,kind,status,sha256,body,
            MATCH(body) AGAINST(%s IN NATURAL LANGUAGE MODE) AS score
            FROM sdd_documents WHERE project_id=%s AND status='active'
            AND MATCH(body) AGAINST(%s IN NATURAL LANGUAGE MODE)>0
            ORDER BY score DESC,path LIMIT 20""", (query, project, query))
        imported = {doc["path"]: doc for doc in documents}
        for row in rows:
            current = imported.get(row["path"])
            if not current or current["sha256"] != row["sha256"] or current["status"] != "active":
                raise ValueError("Source has changed: re-import the project before preparing context")
        self.connection.rollback()  # End the read snapshot before the next invocation.
        return {"project_id": project, "query": query, "sources": rows,
                "fingerprints": project_fingerprints(project, documents)}
