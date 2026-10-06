"""OpenAI and OpenAI-compatible LLM integration."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from openai import OpenAI, APIError, APIConnectionError, RateLimitError, APITimeoutError

from .llm_interface import (
    LLMInterface,
    SYSTEM_PROMPT,
    build_user_prompt,
    validate_categorization_response,
)
from .models import Bookmark

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAYS = [5, 15, 30]
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


class OpenAILLM(LLMInterface):
    """OpenAI (or OpenAI-compatible) LLM provider for bookmark categorization."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = DEFAULT_OPENAI_MODEL,
        client: OpenAI | Any | None = None,
    ):
        self.model = model or DEFAULT_OPENAI_MODEL
        self.api_key = api_key or os.getenv("API_KEY") or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("BASE_URL", "https://api.openai.com/v1")
        if client is not None:
            self.client = client
        else:
            if not self.api_key:
                raise ValueError(
                    "No OpenAI API key provided. Set API_KEY or OPENAI_API_KEY in .env or pass --api-key."
                )
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def categorize_batch(
        self,
        batch: list[Bookmark],
        existing_categories: list[str],
        max_categories: int = 20,
    ) -> dict[str, list[int]]:
        """Categorize a batch of bookmarks using OpenAI."""
        if not batch:
            return {}

        user_prompt = build_user_prompt(batch, existing_categories, max_categories)

        for attempt in range(MAX_RETRIES):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.2,
                    response_format={"type": "json_object"},
                )

                content = response.choices[0].message.content
                try:
                    return validate_categorization_response(content, len(batch))
                except (json.JSONDecodeError, ValueError) as err:
                    logger.warning("Failed to parse OpenAI JSON response: %s", err)
                    return {"Uncategorized": list(range(len(batch)))}

            except RateLimitError as e:
                delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                print(f"  Rate limited. Retrying in {delay}s... (attempt {attempt + 1}/{MAX_RETRIES})")
                time.sleep(delay)
            except APITimeoutError as e:
                delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                print(f"  Request timed out. Retrying in {delay}s... (attempt {attempt + 1}/{MAX_RETRIES})")
                time.sleep(delay)
            except APIConnectionError as e:
                delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                print(f"  Connection error: {e}. Retrying in {delay}s... (attempt {attempt + 1}/{MAX_RETRIES})")
                time.sleep(delay)
            except APIError as e:
                if e.status_code and e.status_code >= 500:
                    delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                    print(f"  Server error ({e.status_code}). Retrying in {delay}s... (attempt {attempt + 1}/{MAX_RETRIES})")
                    time.sleep(delay)
                else:
                    # Client error (4xx) — don't retry
                    print(f"  API error: {e}")
                    return {"Uncategorized": list(range(len(batch)))}

        print(f"  Failed after {MAX_RETRIES} attempts. Marking batch as Uncategorized.")
        return {"Uncategorized": list(range(len(batch)))}
