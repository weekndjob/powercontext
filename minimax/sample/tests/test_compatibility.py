"""Archive change must preserve the taskboard's existing query behavior."""
from copy import deepcopy
from taskboard import list_tasks


def test_archive_empty_input_is_still_empty():
    assert list_tasks([]) == []


def test_archive_change_preserves_status_filter_for_visible_rows():
    rows = [{"id": 1, "status": "open", "archived": False},
            {"id": 2, "status": "done", "archived": False}]
    assert list_tasks(rows, status="done") == [rows[1]]
    assert list_tasks(rows, status="missing") == []


def test_archive_change_preserves_order_and_does_not_mutate_inputs():
    rows = [{"id": 9, "status": "open", "archived": False},
            {"id": 3, "status": "done", "archived": False}]
    before = deepcopy(rows)
    actual = list_tasks(rows)
    assert actual == before
    assert actual is not rows
    assert rows == before
