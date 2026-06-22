from pymidil.utils.project_meta import PyProject


try:
    from importlib.metadata import version

    __version__ = version("pymidil")
except Exception:
    from pathlib import Path

    __version__ = PyProject(
        str(Path(__file__).parent.parent / "pyproject.toml")
    ).version

__service_version__ = PyProject().version
