"""Interface and prompt definitions for LLM providers."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from .models import Bookmark

SYSTEM_PROMPT = """You are a bookmark organizer. You categorize bookmarks into logical folders.

Rules:
- Assign each bookmark to exactly one category.
- STRONGLY PREFER existing categories. Only create a new category if a bookmark truly does not fit any existing one.
- Use short, broad category names (e.g., "Development", "News", "Finance", "Design"). Prefer general categories over highly specific ones.
- Merge similar topics into one category (e.g., "AI", "Machine Learning", and "Data Science" should all go under one category like "AI & Data Science").
- You MUST NOT exceed the maximum number of categories. If you're at the limit, force-fit bookmarks into the closest existing category.
- Return valid JSON only."""


def build_user_prompt(
    batch: list[Bookmark],
    existing_categories: list[str],
    max_categories: int,
) -> str:
    """Build the user prompt for categorizing a batch of bookmarks."""
    bookmark_list = "\n".join(
        f"{i}. {b.title} — {b.url}" for i, b in enumerate(batch)
    )

    existing_cats_str = ", ".join(existing_categories) if existing_categories else "None yet"

    return f"""Categorize these bookmarks into folders.

Existing categories — YOU MUST REUSE THESE whenever possible: {existing_cats_str}
Maximum total categories allowed: {max_categories}
Current category count: {len(existing_categories)}

IMPORTANT: Do NOT create a new category if an existing one is even remotely relevant. Only create a new category as a last resort when nothing fits. Prefer broader groupings.

Bookmarks:
{bookmark_list}

Respond with JSON in this exact format:
{{
  "Category Name": [0, 2, 5],
  "Another Category": [1, 3, 4]
}}

Where the numbers are the bookmark indices from the list above. Every bookmark must be assigned to exactly one category. Use existing category names exactly as written (case-sensitive)."""


def validate_categorization_response(
    raw_content: str | dict[str, Any],
    batch_size: int,
) -> dict[str, list[int]]:
    """
    Validate and clean the JSON categorization response from the LLM.
    Returns category -> list of valid bookmark indices.
    Guarantees every index in the batch is accounted for.
    """
    if isinstance(raw_content, str):
        cleaned = raw_content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
        data = json.loads(cleaned)
    elif isinstance(raw_content, dict):
        data = raw_content
    else:
        raise ValueError(f"Expected str or dict, got {type(raw_content).__name__}")

    if not isinstance(data, dict):
        raise ValueError("Response JSON root must be an object (dict)")

    validated: dict[str, list[int]] = {}
    assigned_indices: set[int] = set()

    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, list):
            continue
        cleaned_key = key.strip()
        if not cleaned_key:
            continue
        if all(isinstance(v, int) for v in value):
            valid_indices = [idx for idx in value if 0 <= idx < batch_size]
            if valid_indices:
                validated[cleaned_key] = valid_indices
                assigned_indices.update(valid_indices)

    # If nothing valid was extracted, place all in Uncategorized
    if not validated:
        return {"Uncategorized": list(range(batch_size))}

    # If any bookmarks were missed by the LLM, assign them to Uncategorized
    missing_indices = [i for i in range(batch_size) if i not in assigned_indices]
    if missing_indices:
        if "Uncategorized" in validated:
            validated["Uncategorized"].extend(missing_indices)
        else:
            validated["Uncategorized"] = missing_indices

    return validated


class LLMInterface(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    def categorize_batch(
        self,
        batch: list[Bookmark],
        existing_categories: list[str],
        max_categories: int = 20,
    ) -> dict[str, list[int]]:
        """Categorize a single batch of bookmarks."""
        pass
