from __future__ import annotations

from typing import Protocol, Union


class MessageProtocol(Protocol):
    """Structural protocol for any message type passed through dispatch hooks."""

    id: Union[str, int]
