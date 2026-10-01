"""Column helpers shared by models."""

import uuid
from datetime import datetime
from typing import Annotated

from sqlalchemy import DateTime, func
from sqlalchemy.orm import mapped_column

UUIDPk = Annotated[uuid.UUID, mapped_column(primary_key=True, default=uuid.uuid4)]
CreatedAt = Annotated[
    datetime, mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
]
UpdatedAt = Annotated[
    datetime,
    mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    ),
]
OptionalTimestamp = Annotated[datetime | None, mapped_column(DateTime(timezone=True))]
