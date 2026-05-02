from __future__ import annotations

from typing import Any, Protocol

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    RateLimitError,
)

from modules.enrichment import (
    EnrichmentJobInput,
    EnrichmentOutput,
    EnrichmentValidationError,
    build_enrichment_messages,
    validate_enrichment_output,
)


class ChatCompletionsParser(Protocol):
    async def parse(self, **kwargs: Any) -> Any:
        """Parse a chat completion into a Pydantic response model."""


class OpenAIEnrichmentError(RuntimeError):
    code = "OPENAI_ENRICHMENT_ERROR"
    retryable = False


class OpenAIEnrichmentAuthError(OpenAIEnrichmentError):
    code = "OPENAI_AUTH_ERROR"


class OpenAIEnrichmentTimeoutError(OpenAIEnrichmentError):
    code = "OPENAI_TIMEOUT"
    retryable = True


class OpenAIEnrichmentRateLimitError(OpenAIEnrichmentError):
    code = "OPENAI_RATE_LIMIT"
    retryable = True


class OpenAIEnrichmentInvalidResponseError(OpenAIEnrichmentError):
    code = "OPENAI_INVALID_RESPONSE"


class OpenAIEnrichmentProviderUnavailableError(OpenAIEnrichmentError):
    code = "OPENAI_PROVIDER_UNAVAILABLE"
    retryable = True


class OpenAIEnrichmentClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        max_retries: int,
        parser: ChatCompletionsParser | None = None,
    ) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )
        self._parser = parser or self._client.chat.completions

    async def enrich_job(self, job: EnrichmentJobInput) -> EnrichmentOutput:
        try:
            response = await self._parser.parse(
                model=self.model,
                messages=build_enrichment_messages(job),
                response_format=EnrichmentOutput,
                temperature=0,
            )
        except AuthenticationError as exc:
            raise OpenAIEnrichmentAuthError("OpenAI authentication failed") from exc
        except APITimeoutError as exc:
            raise OpenAIEnrichmentTimeoutError("OpenAI request timed out") from exc
        except RateLimitError as exc:
            raise OpenAIEnrichmentRateLimitError("OpenAI rate limit exceeded") from exc
        except APIConnectionError as exc:
            raise OpenAIEnrichmentProviderUnavailableError(
                "OpenAI provider connection failed"
            ) from exc
        except APIStatusError as exc:
            if exc.status_code >= 500:
                raise OpenAIEnrichmentProviderUnavailableError(
                    "OpenAI provider unavailable"
                ) from exc
            raise OpenAIEnrichmentInvalidResponseError("OpenAI request failed") from exc

        output = parse_enrichment_response(response)
        try:
            return validate_enrichment_output(output, source_text=job.clean_text())
        except EnrichmentValidationError as exc:
            raise OpenAIEnrichmentInvalidResponseError(str(exc)) from exc


def parse_enrichment_response(response: Any) -> EnrichmentOutput:
    try:
        message = response.choices[0].message
    except (AttributeError, IndexError) as exc:
        raise OpenAIEnrichmentInvalidResponseError("OpenAI response missing message") from exc

    refusal = getattr(message, "refusal", None)
    if refusal:
        raise OpenAIEnrichmentInvalidResponseError("OpenAI response refused enrichment request")

    parsed = getattr(message, "parsed", None)
    if not isinstance(parsed, EnrichmentOutput):
        raise OpenAIEnrichmentInvalidResponseError("OpenAI response did not match schema")
    return parsed
