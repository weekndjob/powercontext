"""A small existing taskboard query module with an archive visibility bug."""


def list_tasks(tasks, status=None, *, include_archived=False):
    """Return matching tasks in input order; archive filtering needs repair."""
    return [task for task in tasks if status is None or task["status"] == status]
