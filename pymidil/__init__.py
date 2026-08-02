"""pymidil — Midil's Python platform SDK."""

from pymidil.exceptions import MidilError
from pymidil.logger.configure import setup_logger
from pymidil.version import __service_version__, __version__

__all__ = ["cli", "__service_version__", "__version__", "MidilError", "setup_logger"]


def __getattr__(name: str):
    if name == "cli":
        # Lazy: the CLI needs the 'cli' extra (click, cookiecutter, …); a bare
        # `import pymidil` must work on a base install.
        try:
            from pymidil.cli.main import cli
        except ImportError as exc:
            raise ImportError(
                f"the midil CLI needs an optional dependency that is not "
                f"installed ({exc.name or exc}) — pip install 'pymidil[cli]'"
            ) from exc
        return cli
    raise AttributeError(f"module 'pymidil' has no attribute {name!r}")
