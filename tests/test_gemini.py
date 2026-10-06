"""Tests for Google Gemini LLM integration and provider factory."""

import json
import pytest
from unittest.mock import MagicMock, patch

from google.genai import errors

from src.gemini_llm import GeminiLLM
from src.llm_factory import detect_provider, create_llm_client
from src.llm_interface import validate_categorization_response, build_user_prompt
from src.models import Bookmark


class TestGeminiLLM:
    def test_init_without_key_raises_error(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("API_KEY", raising=False)
        with pytest.raises(ValueError, match="No Gemini API key provided"):
            GeminiLLM(api_key=None)

    def test_init_with_key(self):
        llm = GeminiLLM(api_key="AIzaSyFakeKey123", model="gemini-3.8-flash")
        assert llm.model == "gemini-3.8-flash"
        assert llm.api_key == "AIzaSyFakeKey123"

    def test_categorize_empty_batch(self):
        llm = GeminiLLM(api_key="AIzaSyFakeKey123")
        res = llm.categorize_batch([], [])
        assert res == {}

    def test_successful_categorization(self):
        mock_genai_client = MagicMock()
        mock_response = MagicMock()
        mock_part = MagicMock()
        mock_part.text = json.dumps({"Dev": [0, 1], "Reading": [2]})
        mock_candidate = MagicMock()
        mock_candidate.content.parts = [mock_part]
        mock_response.candidates = [mock_candidate]
        mock_genai_client.models.generate_content.return_value = mock_response

        llm = GeminiLLM(api_key="AIzaSyFakeKey123", client=mock_genai_client)
        batch = [
            Bookmark(title="GitHub", url="https://github.com"),
            Bookmark(title="GitLab", url="https://gitlab.com"),
            Bookmark(title="Article", url="https://medium.com"),
        ]

        result = llm.categorize_batch(batch, existing_categories=["Dev"])
        assert result == {"Dev": [0, 1], "Reading": [2]}
        mock_genai_client.models.generate_content.assert_called_once()

    def test_invalid_json_fallback_uncategorized(self):
        mock_genai_client = MagicMock()
        mock_response = MagicMock()
        mock_part = MagicMock()
        mock_part.text = "This is not valid json at all"
        mock_candidate = MagicMock()
        mock_candidate.content.parts = [mock_part]
        mock_response.candidates = [mock_candidate]
        mock_genai_client.models.generate_content.return_value = mock_response

        llm = GeminiLLM(api_key="AIzaSyFakeKey123", client=mock_genai_client)
        batch = [Bookmark(title="Example", url="https://example.com")]

        result = llm.categorize_batch(batch, [])
        assert result == {"Uncategorized": [0]}

    def test_missing_indices_assigned_to_uncategorized(self):
        mock_genai_client = MagicMock()
        mock_response = MagicMock()
        mock_part = MagicMock()
        # Model only returned index 0, missing index 1
        mock_part.text = json.dumps({"Dev": [0]})
        mock_candidate = MagicMock()
        mock_candidate.content.parts = [mock_part]
        mock_response.candidates = [mock_candidate]
        mock_genai_client.models.generate_content.return_value = mock_response

        llm = GeminiLLM(api_key="AIzaSyFakeKey123", client=mock_genai_client)
        batch = [
            Bookmark(title="GitHub", url="https://github.com"),
            Bookmark(title="Forgotten", url="https://forgotten.com"),
        ]

        result = llm.categorize_batch(batch, [])
        assert result == {"Dev": [0], "Uncategorized": [1]}

    @patch("time.sleep", return_value=None)
    def test_rate_limit_retry_then_success(self, mock_sleep):
        mock_genai_client = MagicMock()
        rate_err = errors.ClientError(429, {"error": {"message": "Resource exhausted"}}, None)
        
        mock_response = MagicMock()
        mock_part = MagicMock()
        mock_part.text = json.dumps({"Tech": [0]})
        mock_candidate = MagicMock()
        mock_candidate.content.parts = [mock_part]
        mock_response.candidates = [mock_candidate]

        # Fail on first attempt with 429, succeed on second attempt
        mock_genai_client.models.generate_content.side_effect = [rate_err, mock_response]

        llm = GeminiLLM(api_key="AIzaSyFakeKey123", client=mock_genai_client)
        batch = [Bookmark(title="Tech", url="https://tech.com")]

        result = llm.categorize_batch(batch, [])
        assert result == {"Tech": [0]}
        assert mock_genai_client.models.generate_content.call_count == 2
        mock_sleep.assert_called_once()

    def test_client_error_permanent_no_retry(self):
        mock_genai_client = MagicMock()
        client_err = errors.ClientError(400, {"error": {"message": "Invalid argument"}}, None)
        mock_genai_client.models.generate_content.side_effect = client_err

        llm = GeminiLLM(api_key="AIzaSyFakeKey123", client=mock_genai_client)
        batch = [Bookmark(title="Bad", url="https://bad.com")]

        result = llm.categorize_batch(batch, [])
        assert result == {"Uncategorized": [0]}
        # Should not retry for 400 Bad Request
        assert mock_genai_client.models.generate_content.call_count == 1

    def test_backward_compat_categorize_bookmarks(self):
        mock_genai_client = MagicMock()
        mock_response = MagicMock()
        mock_part = MagicMock()
        mock_part.text = json.dumps({"Social": [0]})
        mock_candidate = MagicMock()
        mock_candidate.content.parts = [mock_part]
        mock_response.candidates = [mock_candidate]
        mock_genai_client.models.generate_content.return_value = mock_response

        llm = GeminiLLM(api_key="AIzaSyFakeKey123", client=mock_genai_client)
        dict_bookmarks = [{"title": "Twitter", "url": "https://x.com", "description": ""}]
        res = llm.categorize_bookmarks(dict_bookmarks, [])
        # 1-indexed dictionary output
        assert res == {1: "Social"}


class TestProviderDetectionAndFactory:
    def test_explicit_provider(self):
        assert detect_provider("gemini") == "gemini"
        assert detect_provider("openai") == "openai"

    def test_detect_from_aiza_key(self):
        assert detect_provider(api_key="AIzaSy123456789") == "gemini"

    def test_detect_from_gemini_model(self):
        assert detect_provider(model="gemini-3.8-flash") == "gemini"

    def test_detect_from_openai_model(self):
        assert detect_provider(model="gpt-4o-mini") == "openai"

    def test_detect_from_gemini_env(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyFakeKey")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.delenv("MODEL", raising=False)
        assert detect_provider() == "gemini"

    def test_detect_aiza_key_overrides_default_gpt_model_env(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "AIzaSyFakeGoogleKey")
        monkeypatch.setenv("MODEL", "gpt-4o-mini")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        assert detect_provider() == "gemini"

    def test_create_gemini_client(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyFakeKey")
        client, provider, model = create_llm_client(provider="gemini")
        assert provider == "gemini"
        assert isinstance(client, GeminiLLM)
        assert model == "gemini-3.8-flash"

    def test_create_openai_client(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-fakeopenai123")
        client, provider, model = create_llm_client(provider="openai")
        assert provider == "openai"
        assert model == "gpt-4o-mini"


class TestLLMInterfaceHelpers:
    def test_validate_categorization_response_markdown_block(self):
        raw = """```json
        {
            "Coding": [0, 1]
        }
        ```"""
        result = validate_categorization_response(raw, batch_size=2)
        assert result == {"Coding": [0, 1]}

    def test_build_user_prompt(self):
        batch = [Bookmark(title="Google", url="https://google.com")]
        prompt = build_user_prompt(batch, ["Search"], 10)
        assert "Google — https://google.com" in prompt
        assert "Search" in prompt
        assert "Maximum total categories allowed: 10" in prompt
