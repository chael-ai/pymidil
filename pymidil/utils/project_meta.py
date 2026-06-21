from typing import Any, Optional, List
import tomli


ESSENTIAL_FIELDS: List[str] = [
    "name",
    "version",
    "description",
    "authors",
    "license",
    "readme",
]


class PyProject:
    """
    Utility class for reading essential fields from pyproject.toml
    (specifically the `[tool.poetry]` section).
    """

    def __init__(self, path: str = "./pyproject.toml") -> None:
        self.path = path
        self._data: dict[str, Any] | None = None
        self._load_data()

    def _load_data(self) -> None:
        try:
            with open(self.path, "rb") as toml_file:
                pyproject_data = tomli.load(toml_file)
                self._data = pyproject_data.get("tool", {}).get(
                    "poetry", {}
                ) or pyproject_data.get("project", {})
        except FileNotFoundError:
            self._data = None

    @property
    def data(self) -> Optional[dict[str, Any]]:
        return self._data

    def get(self, key: str, default: Any = None) -> Any:
        """
        Generic getter for any Poetry field.
        """
        if not self._data:
            return default
        return self._data.get(key, default)

    def essentials(self) -> dict[str, Any]:
        """
        Return a dictionary of essential Poetry fields.
        """
        return {key: self.get(key) for key in ESSENTIAL_FIELDS}

    @property
    def name(self) -> str:
        return self.get("name", "")

    @property
    def version(self) -> str:
        return self.get("version", "")

    @property
    def description(self) -> str:
        return self.get("description", "")

    @property
    def authors(self) -> list[str]:
        return self.get("authors", [])

    @property
    def license(self) -> str:
        return self.get("license", "")
