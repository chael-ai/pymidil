from pymidil.utils.project_meta import PyProject


try:
    from importlib.metadata import version

    __version__ = version("midil")
except Exception:
    # Fallback to pyproject.toml version (development mode)
    __version__ = PyProject().version

__service_version__ = PyProject().version
