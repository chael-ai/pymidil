from typing import Optional

import httpx


class DefaultRetryStrategy:
    RETRYABLE_METHODS = frozenset(["HEAD", "GET", "PUT", "DELETE", "OPTIONS", "TRACE"])
    RETRYABLE_STATUS_CODES = frozenset([429, 502, 503, 504, 401, 400])

    def __init__(self, retryable_methods=None, retryable_status_codes=None):
        self.retryable_methods = retryable_methods or self.RETRYABLE_METHODS
        self.retryable_status_codes = (
            retryable_status_codes or self.RETRYABLE_STATUS_CODES
        )

    def should_retry(
        self,
        request: httpx.Request,
        response: Optional[httpx.Response],
        error: Optional[Exception],
    ) -> bool:
        if request.method not in self.retryable_methods:
            return False
        if response and response.status_code in self.retryable_status_codes:
            return True
        if isinstance(error, (httpx.TimeoutException, httpx.HTTPError)):
            return True
        return False
