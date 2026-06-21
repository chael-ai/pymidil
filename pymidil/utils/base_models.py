from pydantic import BaseModel
from typing import Literal, Dict, Any, Callable
from pydantic.main import IncEx
from pymidil.utils.strings import to_snake_case


class SnakeCaseModel(BaseModel):
    def model_dump(
        self,
        *,
        mode: Literal["json", "python"] | str = "python",
        include: IncEx | None = None,
        exclude: IncEx | None = None,
        context: Any | None = None,
        by_alias: bool | None = None,
        exclude_unset: bool = False,
        exclude_defaults: bool = False,
        exclude_none: bool = False,
        round_trip: bool = False,
        warnings: bool | Literal["none", "warn", "error"] = True,
        fallback: Callable[[Any], Any] | None = None,
        serialize_as_any: bool = False,
    ) -> Dict[str, Any]:
        data = BaseModel.model_dump(
            self,
            mode=mode,
            include=include,
            exclude=exclude,
            context=context,
            by_alias=by_alias,
            exclude_unset=exclude_unset,
            exclude_defaults=exclude_defaults,
            exclude_none=exclude_none,
            round_trip=round_trip,
            warnings=warnings,
            fallback=fallback,
            serialize_as_any=serialize_as_any,
        )
        return self._parse_keys_to_snake_case(data)

    def _parse_keys_to_snake_case(self, data: Any) -> Any:
        if isinstance(data, dict):
            return {
                to_snake_case(k): self._parse_keys_to_snake_case(v)
                for k, v in data.items()
            }
        elif isinstance(data, list):
            return [self._parse_keys_to_snake_case(i) for i in data]
        return data
