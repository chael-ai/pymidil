from abc import ABC, abstractmethod


class BaseLauncher(ABC):
    @abstractmethod
    def run(self) -> None:
        pass
