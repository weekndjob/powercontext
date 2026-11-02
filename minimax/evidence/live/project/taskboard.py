"""A small existing taskboard query module with archive visibility support."""


def list_tasks(tasks, status=None, *, include_archived=False):
    """Return matching tasks in input order, optionally including archived tasks."""
    return [
        task
        for task in tasks
        if (include_archived or not task.get("archived", False))
        and (status is None or task["status"] == status)
    ]
