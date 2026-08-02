from pymidil.version import __service_version__, __version__
from pymidil.logger.configure import setup_logger
from pymidil.exceptions import MidilError

__all__ = ["cli", "__service_version__", "__version__", "MidilError", "setup_logger"]


def __getattr__(name: str):
    """Lazy-load the Click CLI so `import pymidil` works without `[cli]`/`[web]`."""
    if name == "cli":
        from pymidil.cli.main import cli

        return cli
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
