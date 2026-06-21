import os


def resolve_hostname() -> str:
    try:
        return os.uname().nodename
    except Exception:
        return "unknown"
