import datetime


def get_time() -> str:
    """Current UTC time."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
