from enum import StrEnum
from pydantic import BaseModel, ConfigDict


class Extra(StrEnum):
    FORBID = "forbid"
    IGNORE = "ignore"
    ALLOW = "allow"


class ForbidExtraFieldsModel(BaseModel):
    model_config = ConfigDict(extra=Extra.FORBID.value)

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if getattr(cls, "model_config", {}).get("extra") != Extra.FORBID.value:
            raise TypeError(f"{cls.__name__}: 'extra' must be 'forbid'")


class AllowExtraFieldsModel(BaseModel):
    model_config = ConfigDict(extra=Extra.ALLOW.value)

    def __init_subclass__(cls, **kwargs):
        BaseModel.__init_subclass__(**kwargs)
        if getattr(cls, "model_config", {}).get("extra") != Extra.ALLOW.value:
            raise TypeError(f"{cls.__name__}: 'extra' must be 'allow'")


class IgnoreExtraFieldsModel(BaseModel):
    model_config = ConfigDict(extra=Extra.IGNORE.value)

    def __init_subclass__(cls, **kwargs):
        BaseModel.__init_subclass__(**kwargs)
        if getattr(cls, "model_config", {}).get("extra") != Extra.IGNORE.value:
            raise TypeError(f"{cls.__name__}: 'extra' must be 'ignore'")
