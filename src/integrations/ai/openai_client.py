from __future__ import annotations

from threading import Lock
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
from modules.jobs import (
    AINormalizationBatchItemResult,
    AINormalizationBatchOutput,
    AINormalizationBatchPromptInput,
    AINormalizationContractError,
    AINormalizationPromptInput,
    CanonicalJobSchema,
    build_ai_normalization_batch_messages,
    build_ai_normalization_messages,
    validate_ai_normalization_batch_output,
    validate_ai_normalization_output,
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


class OpenAINormalizationError(RuntimeError):
    code = "OPENAI_NORMALIZATION_ERROR"
    retryable = False


class OpenAINormalizationAuthError(OpenAINormalizationError):
    code = "OPENAI_AUTH_ERROR"


class OpenAINormalizationTimeoutError(OpenAINormalizationError):
    code = "OPENAI_TIMEOUT"
    retryable = True


class OpenAINormalizationRateLimitError(OpenAINormalizationError):
    code = "OPENAI_RATE_LIMIT"
    retryable = True


class OpenAINormalizationInvalidResponseError(OpenAINormalizationError):
    code = "OPENAI_INVALID_RESPONSE"


class OpenAINormalizationProviderUnavailableError(OpenAINormalizationError):
    code = "OPENAI_PROVIDER_UNAVAILABLE"
    retryable = True


def _empty_metrics() -> dict[str, int]:
    return {"requests": 0, "successes": 0, "rate_limited": 0, "failed": 0}


class OpenAIModelRotator:
    def __init__(self, models: list[str] | tuple[str, ...]) -> None:
        normalized = [model.strip() for model in models if model.strip()]
        if not normalized:
            raise ValueError("OpenAIModelRotator requires at least one model")
        self._models = tuple(normalized)
        self._index = 0
        self._lock = Lock()

    @property
    def models(self) -> tuple[str, ...]:
        return self._models

    def next_model(self) -> str:
        with self._lock:
            model = self._models[self._index]
            self._index = (self._index + 1) % len(self._models)
            return model


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
        model_rotator: OpenAIModelRotator | None = None,
        output_language: str = "english",
    ) -> None:
        self._model_rotator = model_rotator or OpenAIModelRotator((model,))
        self.model = self._model_rotator.models[0]
        self.models = self._model_rotator.models
        self.last_model = self.model
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.output_language = output_language
        self._metrics_lock = Lock()
        self._metrics_by_model: dict[str, dict[str, int]] = {}
        self._metrics_by_request_type: dict[str, dict[str, int]] = {}
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )
        self._parser = parser or self._client.chat.completions

    async def enrich_job(self, job: EnrichmentJobInput) -> EnrichmentOutput:
        selected_model = self._model_rotator.next_model()
        self.last_model = selected_model
        self._record_metrics(selected_model, request_type="enrichment", outcome="request")
        try:
            response = await self._parser.parse(
                model=selected_model,
                messages=build_enrichment_messages(job, output_language=self.output_language),
                response_format=EnrichmentOutput,
                temperature=0,
            )
        except AuthenticationError as exc:
            self._record_metrics(selected_model, request_type="enrichment", outcome="failed")
            raise OpenAIEnrichmentAuthError("OpenAI authentication failed") from exc
        except APITimeoutError as exc:
            self._record_metrics(selected_model, request_type="enrichment", outcome="failed")
            raise OpenAIEnrichmentTimeoutError("OpenAI request timed out") from exc
        except RateLimitError as exc:
            self._record_metrics(selected_model, request_type="enrichment", outcome="rate_limited")
            raise OpenAIEnrichmentRateLimitError("OpenAI rate limit exceeded") from exc
        except APIConnectionError as exc:
            self._record_metrics(selected_model, request_type="enrichment", outcome="failed")
            raise OpenAIEnrichmentProviderUnavailableError(
                "OpenAI provider connection failed"
            ) from exc
        except APIStatusError as exc:
            self._record_metrics(selected_model, request_type="enrichment", outcome="failed")
            if exc.status_code >= 500:
                raise OpenAIEnrichmentProviderUnavailableError(
                    "OpenAI provider unavailable"
                ) from exc
            raise OpenAIEnrichmentInvalidResponseError("OpenAI request failed") from exc

        output = parse_enrichment_response(response)
        try:
            validated = validate_enrichment_output(output, source_text=job.clean_text())
        except EnrichmentValidationError as exc:
            self._record_metrics(selected_model, request_type="enrichment", outcome="failed")
            raise OpenAIEnrichmentInvalidResponseError(str(exc)) from exc
        self._record_metrics(selected_model, request_type="enrichment", outcome="success")
        return validated

    def metrics_snapshot(self) -> dict[str, Any]:
        with self._metrics_lock:
            by_model = {
                model: dict(self._metrics_by_model.get(model, _empty_metrics()))
                for model in self.models
            }
            by_request_type = {
                request_type: dict(metrics)
                for request_type, metrics in sorted(
                    self._metrics_by_request_type.items(),
                    key=lambda item: item[0],
                )
            }
        return {
            "models": list(self.models),
            "byModel": by_model,
            "byRequestType": by_request_type,
        }

    def _record_metrics(self, model: str, *, request_type: str, outcome: str) -> None:
        with self._metrics_lock:
            model_metrics = self._metrics_by_model.setdefault(model, _empty_metrics())
            request_metrics = self._metrics_by_request_type.setdefault(
                request_type,
                _empty_metrics(),
            )
            if outcome == "request":
                model_metrics["requests"] += 1
                request_metrics["requests"] += 1
                return
            if outcome == "success":
                model_metrics["successes"] += 1
                request_metrics["successes"] += 1
                return
            if outcome == "rate_limited":
                model_metrics["rate_limited"] += 1
                model_metrics["failed"] += 1
                request_metrics["rate_limited"] += 1
                request_metrics["failed"] += 1
                return
            model_metrics["failed"] += 1
            request_metrics["failed"] += 1


class OpenAINormalizationClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        max_retries: int,
        parser: ChatCompletionsParser | None = None,
        model_rotator: OpenAIModelRotator | None = None,
        output_language: str = "english",
    ) -> None:
        self._model_rotator = model_rotator or OpenAIModelRotator((model,))
        self.model = self._model_rotator.models[0]
        self.models = self._model_rotator.models
        self.last_model = self.model
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.output_language = output_language
        self._metrics_lock = Lock()
        self._metrics_by_model: dict[str, dict[str, int]] = {}
        self._metrics_by_request_type: dict[str, dict[str, int]] = {}
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )
        self._parser = parser or self._client.chat.completions

    async def normalize_job(self, prompt_input: AINormalizationPromptInput) -> CanonicalJobSchema:
        selected_model = self._model_rotator.next_model()
        self.last_model = selected_model
        self._record_metrics(selected_model, request_type="normalization", outcome="request")
        try:
            response = await self._parser.parse(
                model=selected_model,
                messages=build_ai_normalization_messages(prompt_input),
                response_format=CanonicalJobSchema,
                temperature=0,
            )
        except AuthenticationError as exc:
            self._record_metrics(selected_model, request_type="normalization", outcome="failed")
            raise OpenAINormalizationAuthError("OpenAI authentication failed") from exc
        except APITimeoutError as exc:
            self._record_metrics(selected_model, request_type="normalization", outcome="failed")
            raise OpenAINormalizationTimeoutError("OpenAI request timed out") from exc
        except RateLimitError as exc:
            self._record_metrics(
                selected_model,
                request_type="normalization",
                outcome="rate_limited",
            )
            raise OpenAINormalizationRateLimitError("OpenAI rate limit exceeded") from exc
        except APIConnectionError as exc:
            self._record_metrics(selected_model, request_type="normalization", outcome="failed")
            raise OpenAINormalizationProviderUnavailableError(
                "OpenAI provider connection failed"
            ) from exc
        except APIStatusError as exc:
            self._record_metrics(selected_model, request_type="normalization", outcome="failed")
            if exc.status_code >= 500:
                raise OpenAINormalizationProviderUnavailableError(
                    "OpenAI provider unavailable"
                ) from exc
            raise OpenAINormalizationInvalidResponseError("OpenAI request failed") from exc

        output = parse_normalization_response(response)
        try:
            validated = validate_ai_normalization_output(output, prompt_input=prompt_input)
        except AINormalizationContractError as exc:
            self._record_metrics(selected_model, request_type="normalization", outcome="failed")
            raise OpenAINormalizationInvalidResponseError(str(exc)) from exc
        self._record_metrics(selected_model, request_type="normalization", outcome="success")
        return validated

    async def normalize_jobs(
        self,
        prompt_input: AINormalizationBatchPromptInput,
    ) -> list[AINormalizationBatchItemResult]:
        selected_model = self._model_rotator.next_model()
        self.last_model = selected_model
        self._record_metrics(selected_model, request_type="normalization", outcome="request")
        try:
            response = await self._parser.parse(
                model=selected_model,
                messages=build_ai_normalization_batch_messages(prompt_input),
                response_format=AINormalizationBatchOutput,
                temperature=0,
            )
        except AuthenticationError as exc:
            self._record_metrics(selected_model, request_type="normalization", outcome="failed")
            raise OpenAINormalizationAuthError("OpenAI authentication failed") from exc
        except APITimeoutError as exc:
            self._record_metrics(selected_model, request_type="normalization", outcome="failed")
            raise OpenAINormalizationTimeoutError("OpenAI request timed out") from exc
        except RateLimitError as exc:
            self._record_metrics(
                selected_model,
                request_type="normalization",
                outcome="rate_limited",
            )
            raise OpenAINormalizationRateLimitError("OpenAI rate limit exceeded") from exc
        except APIConnectionError as exc:
            self._record_metrics(selected_model, request_type="normalization", outcome="failed")
            raise OpenAINormalizationProviderUnavailableError(
                "OpenAI provider connection failed"
            ) from exc
        except APIStatusError as exc:
            self._record_metrics(selected_model, request_type="normalization", outcome="failed")
            if exc.status_code >= 500:
                raise OpenAINormalizationProviderUnavailableError(
                    "OpenAI provider unavailable"
                ) from exc
            raise OpenAINormalizationInvalidResponseError("OpenAI request failed") from exc

        output = parse_normalization_batch_response(response)
        try:
            validated = validate_ai_normalization_batch_output(output, prompt_input=prompt_input)
        except AINormalizationContractError as exc:
            self._record_metrics(selected_model, request_type="normalization", outcome="failed")
            raise OpenAINormalizationInvalidResponseError(str(exc)) from exc
        self._record_metrics(selected_model, request_type="normalization", outcome="success")
        return validated

    def metrics_snapshot(self) -> dict[str, Any]:
        with self._metrics_lock:
            by_model = {
                model: dict(self._metrics_by_model.get(model, _empty_metrics()))
                for model in self.models
            }
            by_request_type = {
                request_type: dict(metrics)
                for request_type, metrics in sorted(
                    self._metrics_by_request_type.items(),
                    key=lambda item: item[0],
                )
            }
        return {
            "models": list(self.models),
            "byModel": by_model,
            "byRequestType": by_request_type,
        }

    def _record_metrics(self, model: str, *, request_type: str, outcome: str) -> None:
        with self._metrics_lock:
            model_metrics = self._metrics_by_model.setdefault(model, _empty_metrics())
            request_metrics = self._metrics_by_request_type.setdefault(
                request_type,
                _empty_metrics(),
            )
            if outcome == "request":
                model_metrics["requests"] += 1
                request_metrics["requests"] += 1
                return
            if outcome == "success":
                model_metrics["successes"] += 1
                request_metrics["successes"] += 1
                return
            if outcome == "rate_limited":
                model_metrics["rate_limited"] += 1
                model_metrics["failed"] += 1
                request_metrics["rate_limited"] += 1
                request_metrics["failed"] += 1
                return
            model_metrics["failed"] += 1
            request_metrics["failed"] += 1


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


def parse_normalization_response(response: Any) -> dict[str, Any] | str:
    try:
        message = response.choices[0].message
    except (AttributeError, IndexError) as exc:
        raise OpenAINormalizationInvalidResponseError("OpenAI response missing message") from exc

    refusal = getattr(message, "refusal", None)
    if refusal:
        raise OpenAINormalizationInvalidResponseError(
            "OpenAI response refused normalization request"
        )

    parsed = getattr(message, "parsed", None)
    if isinstance(parsed, CanonicalJobSchema):
        return parsed.model_dump(mode="python")
    if isinstance(parsed, dict):
        return parsed
    raise OpenAINormalizationInvalidResponseError("OpenAI response did not match schema")


def parse_normalization_batch_response(
    response: Any,
) -> AINormalizationBatchOutput | dict[str, Any] | str:
    try:
        message = response.choices[0].message
    except (AttributeError, IndexError) as exc:
        raise OpenAINormalizationInvalidResponseError("OpenAI response missing message") from exc

    refusal = getattr(message, "refusal", None)
    if refusal:
        raise OpenAINormalizationInvalidResponseError(
            "OpenAI response refused normalization request"
        )

    parsed = getattr(message, "parsed", None)
    if isinstance(parsed, AINormalizationBatchOutput):
        return parsed
    if isinstance(parsed, dict):
        return parsed
    raise OpenAINormalizationInvalidResponseError("OpenAI response did not match batch schema")
