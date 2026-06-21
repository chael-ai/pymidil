from typing import Union, Optional, Sequence, Mapping, Dict, Any
from pymidil.jsonapi.config import AllowExtraFieldsModel
from datetime import datetime
from pydantic import Field
from pymidil.utils.time import utcnow

MessageBody = Sequence[Any] | Mapping[Any, Any] | str


class Message(AllowExtraFieldsModel):
    id: Union[str, int] = Field(
        ...,
        description="Unique identifier for the message or its position, You can rely on the message Id for idempotent",
    )
    body: MessageBody = Field(..., description="The actual message payload")
    timestamp: Optional[datetime] = Field(
        default_factory=utcnow, description="When the message was published or received"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional message properties or headers"
    )
