import datetime

def get_time():
    """Current UTC time."""
    return datetime.datetime.utcnow().isoformat()
