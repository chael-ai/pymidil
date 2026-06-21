from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

from pymidil.web.pagination.strategies.cursor.encoders.base import (
    CursorEncoder,
)
from pymidil.web.pagination.strategies.cursor.exceptions import (
    ExpiredCursorError,
    InvalidCursorError,
)
from pymidil.web.pagination.strategies.cursor.models import (
    CursorPayload,
)
from pymidil.web.pagination.strategies.cursor.config import HMACCursorConfig


class HMACCursorEncoder(CursorEncoder):
    def __init__(
        self,
        *,
        config: HMACCursorConfig,
    ) -> None:
        self._config = config
        self._secret_key = config.secret_key.encode()
        self._expires_in_seconds = config.expires_in_seconds

    def encode(
        self,
        payload: CursorPayload,
    ) -> str:
        payload = self._enrich_payload(payload)

        payload_json = json.dumps(
            payload.model_dump(mode="json"),
            separators=(",", ":"),
            sort_keys=True,
        )

        payload_b64 = self._base64_encode(
            payload_json.encode(),
        )

        signature = self._generate_signature(
            payload_b64,
        )

        return f"{payload_b64}.{signature}"

    def decode(
        self,
        cursor: str,
    ) -> CursorPayload:
        try:
            payload_b64, signature = cursor.split(".", 1)

        except ValueError:
            raise InvalidCursorError("Malformed cursor.")

        expected_signature = self._generate_signature(
            payload_b64,
        )

        if not hmac.compare_digest(
            signature,
            expected_signature,
        ):
            raise InvalidCursorError("Invalid cursor signature.")

        try:
            payload_json = self._base64_decode(
                payload_b64,
            ).decode()

            payload_data = json.loads(
                payload_json,
            )

        except Exception as exc:
            raise InvalidCursorError("Failed to decode cursor.") from exc

        payload = CursorPayload.model_validate(
            payload_data,
        )

        self._validate_expiry(payload)

        return payload

    def _enrich_payload(
        self,
        payload: CursorPayload,
    ) -> CursorPayload:
        if payload.expires_at is None and self._expires_in_seconds:
            return payload.model_copy(
                update={
                    "expires_at": (
                        datetime.now(UTC)
                        + timedelta(
                            seconds=self._expires_in_seconds,
                        )
                    )
                }
            )

        return payload

    def _validate_expiry(
        self,
        payload: CursorPayload,
    ) -> None:
        if payload.expires_at is None:
            return

        if datetime.now(UTC) > payload.expires_at:
            raise ExpiredCursorError("Cursor expired.")

    def _generate_signature(
        self,
        payload_b64: str,
    ) -> str:
        digest = hmac.new(
            self._secret_key,
            payload_b64.encode(),
            hashlib.sha256,
        ).digest()

        return self._base64_encode(digest)

    @staticmethod
    def _base64_encode(
        data: bytes,
    ) -> str:
        return base64.urlsafe_b64encode(data).decode().rstrip("=")

    @staticmethod
    def _base64_decode(
        data: str,
    ) -> bytes:
        padding = "=" * (-len(data) % 4)

        return base64.urlsafe_b64decode(
            data + padding,
        )
