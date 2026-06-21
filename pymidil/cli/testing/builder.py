# midil/core/testing/builder.py
from pathlib import Path
from pymidil.cli.testing.options import TestOptions


class PytestCommandBuilder:
    def __init__(self, options: TestOptions):
        self.options = options
        self.command: list[str] = []

    def determine_runner(self) -> "PytestCommandBuilder":
        if Path("pyproject.toml").exists():
            self.command = ["poetry", "run", "pytest"]
        else:
            self.command = ["python", "-m", "pytest"]
        return self

    def add_options(self) -> "PytestCommandBuilder":
        if self.options.verbose:
            self.command.append("-v")

        if self.options.coverage or self.options.html_cov:
            self.command.extend(["--cov=midil", "--cov-report=term-missing"])

            if self.options.html_cov:
                self.command.append("--cov-report=html")

        if self.options.file:
            path = Path(self.options.file)
            if not path.exists():
                raise FileNotFoundError(
                    f"Test path '{self.options.file}' does not exist"
                )
            self.command.append(str(path))

        self.command.extend(
            ["--strict-markers", "--strict-config", "-p", "pytest_asyncio"]
        )
        return self

    def build(self) -> list[str]:
        return self.command
