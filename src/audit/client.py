"""Resilient Google Gemini API client factory and retry utilities."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({408, 429, 500, 502, 503, 504})


def create_gemini_client(api_key: str | None = None) -> genai.Client:
    """Initializes a configured Google GenAI client from explicit or environment credentials."""
    resolved_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not resolved_key:
        raise ValueError(
            "GEMINI_API_KEY not found in environment or .env file. "
            "Please configure GEMINI_API_KEY before executing inference."
        )
    return genai.Client(api_key=resolved_key)


def generate_content_with_retry(
    client: genai.Client,
    model: str,
    contents: list[Any],
    config: types.GenerateContentConfig,
    max_retries: int = 3,
    base_delay_seconds: float = 1.0,
) -> Any:
    """Executes client.models.generate_content with exponential backoff for transient API errors."""
    attempt = 0
    while True:
        try:
            return client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
        except genai_errors.APIError as exc:
            attempt += 1
            status_code = getattr(exc, "code", None)
            if attempt > max_retries or (
                status_code is not None
                and status_code not in _RETRYABLE_STATUS_CODES
            ):
                raise
            sleep_time = base_delay_seconds * (2 ** (attempt - 1))
            logger.warning(
                "Transient Gemini APIError (status=%s) on attempt %d/%d; retrying in %.1fs...",
                status_code,
                attempt,
                max_retries,
                sleep_time,
            )
            time.sleep(sleep_time)
