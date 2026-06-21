import contextvars
from contextlib import asynccontextmanager
from uuid import uuid4
from typing import Optional, AsyncGenerator, Union, Final, cast


class EventContext:
    def __init__(
        self,
        id: str,
        event_type: str,
        parent: Optional["EventContext"] = None,
    ) -> None:
        self.id: str = id
        self.event_type: str = event_type
        self.parent: Optional[EventContext] = parent

    def __repr__(self) -> str:
        return (
            f"<EventContext id={self.id} type={self.event_type} "
            f"parent={self.parent.id if self.parent else None}>"
        )


# Sentinel to distinguish between "not provided" and "explicit None"
NOTSET: Final = object()

# Context variable to hold the current EventContext
_current_event_context: contextvars.ContextVar[EventContext] = contextvars.ContextVar(
    "event"
)


def get_current_event() -> Optional[EventContext]:
    """
    Get the current event context from the context variable.
    Raises a LookupError if no context is set.
    """
    try:
        return _current_event_context.get()
    except LookupError:
        return None


@asynccontextmanager
async def event_context(
    event_type: str,
    id: Optional[str] = None,
    parent_override: Union[Optional[EventContext], object] = NOTSET,
) -> AsyncGenerator[EventContext, None]:
    """
    Async context manager that sets a new EventContext for the current execution scope.

    :param event_type: Type of the event
    :param parent_override: Explicit parent context to use, or omit to use current context if available.
                            Use None to explicitly set no parent.
    :return: Yields the new EventContext for the block
    """
    if parent_override is NOTSET:
        try:
            parent = _current_event_context.get()
        except LookupError:
            parent = None
    else:
        parent = cast(Optional[EventContext], parent_override)

    new_context = EventContext(
        id=id or uuid4().hex,
        event_type=event_type,
        parent=parent,
    )

    token = _current_event_context.set(new_context)
    try:
        yield new_context
    finally:
        _current_event_context.reset(token)
