from pathlib import Path
from abc import ABC, abstractmethod
from typing import Iterable, Optional


class ProjectHook(ABC):
    """Abstract base class for project post-generation hooks."""

    @abstractmethod
    def execute(self) -> None:
        pass


class ListProcessingHook(ProjectHook, ABC):
    """Base hook that processes a list of string paths/items."""

    def __init__(self, items: Optional[Iterable[str]] = None):
        self.items = list(items or [])

    @abstractmethod
    def process_item(self, item: str) -> None:
        pass

    def execute(self) -> None:
        for item in self.items:
            self.process_item(item)


class ConditionalFileRemover(ListProcessingHook):
    """Removes files based on user configuration choices."""

    def __init__(self, docker_flag: str, files: Optional[Iterable[str]] = None):
        default_files = ["Dockerfile", "docker-compose.yml"]
        super().__init__(files or default_files)
        self.docker_flag = docker_flag

    def execute(self) -> None:
        if self.docker_flag != "y":
            super().execute()

    def process_item(self, item: str) -> None:
        path = Path(item)
        if path.exists():
            path.unlink()


class DirectoryCreator(ListProcessingHook):
    """Creates additional directories for project structure."""

    def __init__(self, directories: Optional[Iterable[str]] = None):
        super().__init__(directories or ["tests"])

    def process_item(self, item: str) -> None:
        Path(item).mkdir(parents=True, exist_ok=True)


class FileCreator(ListProcessingHook):
    """Creates .py files for Python packages."""

    def __init__(self, files: Optional[Iterable[str]] = None):
        super().__init__(files or ["tests/__init__.py"])

    def process_item(self, item: str) -> None:
        Path(item).touch()


class PostGenProjectManager:
    """Coordinates execution of post-generation hooks."""

    def __init__(self, hooks: Iterable[ProjectHook]):
        self.hooks = list(hooks)

    def run(self) -> None:
        for hook in self.hooks:
            hook.execute()
