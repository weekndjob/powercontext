"""Target behavior from ARCHIVE-002; identical tests run before and after."""
from taskboard import list_tasks


ROWS = [
    {"id": 1, "status": "open", "archived": False},
    {"id": 2, "status": "open", "archived": True},
    {"id": 3, "status": "done", "archived": False},
    {"id": 4, "status": "done", "archived": True},
]


def test_archive_is_excluded_by_default():
    assert [row["id"] for row in list_tasks(ROWS)] == [1, 3]


def test_explicit_false_also_excludes_archive():
    assert [row["id"] for row in list_tasks(ROWS, include_archived=False)] == [1, 3]


def test_archive_status_filter_is_an_intersection():
    assert [row["id"] for row in list_tasks(ROWS, status="open")] == [1]


def test_archive_can_be_explicitly_included():
    assert [row["id"] for row in list_tasks(ROWS, include_archived=True)] == [1, 2, 3, 4]


def test_including_archive_does_not_bypass_status():
    assert [row["id"] for row in list_tasks(ROWS, status="done", include_archived=True)] == [3, 4]
