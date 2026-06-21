from abc import ABC, abstractmethod


class ProjectScaffolder(ABC):
    """
    Abstract base class for project scaffolding.
    """

    @abstractmethod
    def scaffold(self, name: str) -> None:
        pass
