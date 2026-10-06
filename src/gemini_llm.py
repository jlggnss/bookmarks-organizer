"""Gemini LLM integration using the official google-genai SDK."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from google import genai
from google.genai import types, errors

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
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"


class GeminiLLM(LLMInterface):
    """Google Gemini LLM provider for bookmark categorization."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_GEMINI_MODEL,
        client: genai.Client | None = None,
    ):
        self.model = model or DEFAULT_GEMINI_MODEL
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("API_KEY")
        if client is not None:
            self.client = client
        else:
            if not self.api_key:
                raise ValueError(
                    "No Gemini API key provided. Set GEMINI_API_KEY in .env or pass --api-key."
                )
            self.client = genai.Client(api_key=self.api_key)

    def categorize_batch(
        self,
        batch: list[Bookmark],
        existing_categories: list[str],
        max_categories: int = 20,
    ) -> dict[str, list[int]]:
        """Categorize a batch of bookmarks using Gemini."""
        if not batch:
            return {}

        user_prompt = build_user_prompt(batch, existing_categories, max_categories)

        for attempt in range(MAX_RETRIES):
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        temperature=0.2,
                        response_mime_type="application/json",
                    ),
                )

                content = self._extract_text(response)
                try:
                    return validate_categorization_response(content, len(batch))
                except (json.JSONDecodeError, ValueError) as err:
                    logger.warning("Failed to parse Gemini JSON response: %s", err)
                    return {"Uncategorized": list(range(len(batch)))}

            except errors.ClientError as e:
                code = getattr(e, "code", None)
                if code == 429:
                    delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                    print(f"  Gemini rate limited (429). Retrying in {delay}s... (attempt {attempt + 1}/{MAX_RETRIES})")
                    time.sleep(delay)
                else:
                    msg = getattr(e, "message", str(e))
                    print(f"  Gemini API client error ({code}): {msg}")
                    return {"Uncategorized": list(range(len(batch)))}

            except errors.ServerError as e:
                code = getattr(e, "code", 500)
                delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                print(f"  Gemini server error ({code}). Retrying in {delay}s... (attempt {attempt + 1}/{MAX_RETRIES})")
                time.sleep(delay)

            except (errors.APIError, Exception) as e:
                err_str = str(e).lower()
                if any(k in err_str for k in ("rate", "quota", "timeout", "connect", "resource_exhausted")):
                    delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                    print(f"  Gemini transient error ({e}). Retrying in {delay}s... (attempt {attempt + 1}/{MAX_RETRIES})")
                    time.sleep(delay)
                else:
                    print(f"  Gemini error: {e}")
                    return {"Uncategorized": list(range(len(batch)))}

        print(f"  Failed after {MAX_RETRIES} attempts. Marking batch as Uncategorized.")
        return {"Uncategorized": list(range(len(batch)))}

    def _extract_text(self, response: Any) -> str:
        """Extract text from Gemini response, avoiding thought parts warning."""
        if hasattr(response, "candidates") and response.candidates:
            parts = []
            for candidate in response.candidates:
                if hasattr(candidate, "content") and hasattr(candidate.content, "parts"):
                    for part in candidate.content.parts:
                        text = getattr(part, "text", None)
                        if text:
                            parts.append(text)
            if parts:
                return "".join(parts)
        if hasattr(response, "text") and response.text:
            return response.text
        return ""

    def categorize_bookmarks(
        self,
        bookmarks: list[dict] | list[Bookmark],
        existing_categories: list[str],
        is_first_iteration: bool = False,
    ) -> dict[int, str]:
        """Backward-compatibility method for dict-based bookmark inputs."""
        bookmark_objs: list[Bookmark] = []
        for b in bookmarks:
            if isinstance(b, Bookmark):
                bookmark_objs.append(b)
            elif isinstance(b, dict):
                bookmark_objs.append(
                    Bookmark(
                        title=b.get("title", ""),
                        url=b.get("url", ""),
                        add_date=b.get("add_date", ""),
                    )
                )

        batch_res = self.categorize_batch(
            bookmark_objs,
            existing_categories if not is_first_iteration else [],
        )

        res: dict[int, str] = {}
        for cat, indices in batch_res.items():
            for idx in indices:
                res[idx + 1] = cat
        return res