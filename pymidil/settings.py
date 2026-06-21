from typing import Dict, Optional, Literal, Any
from pydantic_settings import BaseSettings, SettingsConfigDict
from pymidil.exceptions import (
    SettingsError,
    AuthSettingsError,
    EventSettingsError,
    ApiSettingsError,
)
from pymidil.auth.config import AuthConfig
from pymidil.web.config import MidilApiConfig
from pymidil.logger.config import LoggerConfig
from pymidil.event.config import (
    EventConfig,
    ConsumerConfig,
    ProducerConfig,
    EventConsumerType,
    EventProducerType,
)
from functools import lru_cache
from pydantic import Field

__all__ = [
    "MidilSettings",
    "LoggerSettings",
    "ApiSettings",
    "SettingsError",
    "AuthSettingsError",
    "EventSettingsError",
    "ApiSettingsError",
    "get_settings",
]


class _BaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MIDIL__",
        env_file=".env",
        env_nested_delimiter="__",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


class LoggerSettings(_BaseSettings):
    logger: LoggerConfig = Field(default=LoggerConfig())


class ApiSettings(_BaseSettings):
    api: MidilApiConfig = Field(default=MidilApiConfig())


class MidilSettings(_BaseSettings):
    api: Optional[MidilApiConfig] = None
    auth: Optional[AuthConfig] = None
    event: Optional[EventConfig] = None
    logger: Optional[LoggerConfig] = None

    def model_post_init(self, __context: Any) -> None:
        if self.event and self.event.consumers is None and self.event.producers is None:
            raise EventSettingsError(
                "Event settings are configured but contain no producers or consumers. "
                "Ensure at least one producer or consumer is defined in MIDIL__EVENT."
            )

    def get_api(self) -> MidilApiConfig:
        if self.api is None:
            raise ApiSettingsError(
                "API settings are not configured. Ensure MIDIL__API is set in the .env file."
            )
        return self.api

    def get_auth(self, expected: Literal["cognito"]) -> AuthConfig:
        if self.auth is None:
            raise AuthSettingsError(
                f"Authentication settings for '{expected}' not configured. "
                "Ensure MIDIL__AUTH is set in the .env file."
            )
        if self.auth.type != expected:
            raise AuthSettingsError(
                f"Expected auth type '{expected}', got '{self.auth.type}'. "
                "Check MIDIL__AUTH__TYPE in the .env file."
            )
        return self.auth

    def get_event(self) -> EventConfig:
        if self.event is None:
            raise EventSettingsError(
                "Event settings are not configured. Ensure MIDIL__EVENT is set in the .env file."
            )
        return self.event

    def get_logger(self) -> LoggerConfig:
        if self.logger is None:
            return LoggerConfig()
        return self.logger

    def get_consumer(self, name: str) -> ConsumerConfig:
        name = name.lower()
        consumers = self.get_event().consumers
        if consumers is None:
            raise EventSettingsError(
                "No consumer configurations found. Ensure MIDIL__EVENT__CONSUMERS is set."
            )
        try:
            return consumers[name]
        except KeyError:
            available = list(consumers.keys())
            raise EventSettingsError(
                f"Consumer '{name}' not found. Available consumers: {available}. "
                "Check MIDIL__EVENT__CONSUMERS in the .env file."
            )

    def get_producer(self, name: str) -> ProducerConfig:
        name = name.lower()
        producers = self.get_event().producers
        if producers is None:
            raise EventSettingsError(
                "No producer configurations found. Ensure MIDIL__EVENT__PRODUCERS is set."
            )
        try:
            return producers[name]
        except KeyError:
            available = list(producers.keys())
            raise EventSettingsError(
                f"Producer '{name}' not found. Available producers: {available}. "
                "Check MIDIL__EVENT__PRODUCERS in the .env file."
            )

    def get_consumers_by_type(
        self, type: EventConsumerType
    ) -> Dict[str, ConsumerConfig]:
        consumers = self.get_event().consumers
        if consumers is None:
            raise EventSettingsError(
                "No consumer configurations found. Ensure MIDIL__EVENT__CONSUMERS is set."
            )
        filtered = {
            name: consumer
            for name, consumer in consumers.items()
            if consumer.type == type.value
        }
        if not filtered:
            raise EventSettingsError(
                f"No consumer configurations with type '{type}'. Available types: "
                f"{[c.type for c in consumers.values()]}. Check MIDIL__EVENT__CONSUMERS."
            )
        return filtered

    def get_producers_by_type(
        self, type: EventProducerType
    ) -> Dict[str, ProducerConfig]:
        producers = self.get_event().producers
        if producers is None:
            raise EventSettingsError(
                "No producer configurations found. Ensure MIDIL__EVENT__PRODUCERS is set."
            )
        filtered = {
            name: producer
            for name, producer in producers.items()
            if producer.type == type.value
        }
        if not filtered:
            raise EventSettingsError(
                f"No producer configurations with type '{type}'. Available types: "
                f"{[p.type for p in producers.values()]}. Check MIDIL__EVENT__PRODUCERS."
            )
        return filtered

    def list_consumers(self) -> Dict[str, str]:
        consumers = self.get_event().consumers
        return (
            {name: consumer.type for name, consumer in consumers.items()}
            if consumers
            else {}
        )

    def list_producers(self) -> Dict[str, str]:
        producers = self.get_event().producers
        return (
            {name: producer.type for name, producer in producers.items()}
            if producers
            else {}
        )


@lru_cache(maxsize=1)
def get_settings() -> MidilSettings:
    """Get the singleton MidilSettings instance, cached for performance."""
    return MidilSettings()
