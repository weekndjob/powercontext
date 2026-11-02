# ARCHIVE-002: current archive visibility contract

Status: active. Supersedes ARCHIVE-001.

Task: fix the archive filter in taskboard.list_tasks.

- R1: With include_archived=False (the default), exclude every archived row.
- R2: With include_archived=True, allow archived and non-archived rows.
- R3: A non-None status is an additional intersection filter, including when
  include_archived=True. An archived row must not bypass the status filter.
- C1: Preserve input order, return a fresh list, and do not modify input rows.
- C2: Preserve empty-input behavior and the existing status=None behavior.

Target tests: tests/test_archive.py. Compatibility: tests/test_compatibility.py.
Implementation: taskboard.py::list_tasks.

archive-spec-updated: R1-C2 remain required after a task handoff.
