"""Local boundary checks only; these do not count as real MiniMax execution."""
import json
import shutil
from pathlib import Path

import httpx
import pytest

from sdd_context.agent import generate_change
from sdd_context.repository import load_documents


def test_model_cannot_change_tests_or_other_files(tmp_path, monkeypatch):
    project = tmp_path / "project"
    shutil.copytree(Path(__file__).resolve().parents[1] / "sample", project)
    _, documents = load_documents(project)
    context = {"sources": documents, "task_id": "archive-filter"}
    monkeypatch.setenv("MINIMAX_API_KEY", "unit-test-placeholder")
    original_client = httpx.Client

    def answer(request):
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps({"path": "tests/test_archive.py", "content": "# forbidden"})}}]})

    monkeypatch.setattr(httpx, "Client", lambda **kw: original_client(transport=httpx.MockTransport(answer), **kw))
    before = (project / "tests/test_archive.py").read_bytes()
    with pytest.raises(ValueError, match="unauthorized"):
        generate_change(context, project, tmp_path / "unit-only-evidence")
    assert (project / "tests/test_archive.py").read_bytes() == before


def test_missing_minimax_credentials_cannot_produce_development_record(tmp_path, monkeypatch):
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    with pytest.raises(ValueError, match="MINIMAX_API_KEY"):
        generate_change({}, tmp_path, tmp_path / "records")
    assert not (tmp_path / "records").exists()
