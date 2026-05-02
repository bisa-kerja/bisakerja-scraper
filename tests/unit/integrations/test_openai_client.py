from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from openai import APIStatusError, APITimeoutError, AuthenticationError, RateLimitError

from integrations.ai import (
    OpenAIEnrichmentAuthError,
    OpenAIEnrichmentClient,
    OpenAIEnrichmentInvalidResponseError,
    OpenAIEnrichmentProviderUnavailableError,
    OpenAIEnrichmentRateLimitError,
    OpenAIEnrichmentTimeoutError,
)
from modules.enrichment import (
    EnrichedRequirement,
    EnrichedSkill,
    EnrichmentJobInput,
    EnrichmentOutput,
    RequirementType,
)


def test_openai_client_uses_custom_base_url_timeout_and_retry_config() -> None:
    client = OpenAIEnrichmentClient(
        api_key="test-key",
        base_url="https://openai-compatible.example.test/v1",
        model="gpt-4o-mini",
        timeout_seconds=12,
        max_retries=3,
        parser=FakeParser(make_output()),
    )

    assert str(client._client.base_url) == "https://openai-compatible.example.test/v1/"
    assert client._client.timeout == 12
    assert client._client.max_retries == 3


@pytest.mark.asyncio
async def test_openai_client_returns_structured_enrichment_output() -> None:
    parser = FakeParser(make_output())
    client = make_client(parser)

    output = await client.enrich_job(make_job_input())

    assert output.skills[0].name == "Python"
    assert parser.calls[0]["response_format"] is EnrichmentOutput
    assert parser.calls[0]["temperature"] == 0


@pytest.mark.asyncio
async def test_openai_client_maps_auth_error() -> None:
    client = make_client(FakeParser(exc=openai_status_error(AuthenticationError, 401)))

    with pytest.raises(OpenAIEnrichmentAuthError):
        await client.enrich_job(make_job_input())


@pytest.mark.asyncio
async def test_openai_client_maps_timeout_error() -> None:
    client = make_client(FakeParser(exc=APITimeoutError(request=httpx.Request("POST", "/"))))

    with pytest.raises(OpenAIEnrichmentTimeoutError):
        await client.enrich_job(make_job_input())


@pytest.mark.asyncio
async def test_openai_client_maps_rate_limit_error() -> None:
    client = make_client(FakeParser(exc=openai_status_error(RateLimitError, 429)))

    with pytest.raises(OpenAIEnrichmentRateLimitError):
        await client.enrich_job(make_job_input())


@pytest.mark.asyncio
async def test_openai_client_maps_server_error_as_provider_unavailable() -> None:
    client = make_client(FakeParser(exc=openai_status_error(APIStatusError, 503)))

    with pytest.raises(OpenAIEnrichmentProviderUnavailableError):
        await client.enrich_job(make_job_input())


@pytest.mark.asyncio
async def test_openai_client_rejects_invalid_parsed_response() -> None:
    client = make_client(FakeParser(parsed={"skills": []}))

    with pytest.raises(OpenAIEnrichmentInvalidResponseError):
        await client.enrich_job(make_job_input())


@pytest.mark.asyncio
async def test_openai_client_rejects_hallucinated_output() -> None:
    output = EnrichmentOutput(
        skills=[EnrichedSkill(name="Kubernetes", confidence=0.9)],
        requirements=[],
        confidence=0.9,
        warnings=[],
    )
    client = make_client(FakeParser(output))

    with pytest.raises(OpenAIEnrichmentInvalidResponseError):
        await client.enrich_job(make_job_input())


def make_client(parser: FakeParser) -> OpenAIEnrichmentClient:
    return OpenAIEnrichmentClient(
        api_key="test-key",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
        timeout_seconds=10,
        max_retries=2,
        parser=parser,
    )


def make_job_input() -> EnrichmentJobInput:
    return EnrichmentJobInput(
        title="Backend Engineer",
        description="Build APIs with Python and PostgreSQL.",
        requirements="3 years backend experience.",
        company="Bisakerja",
        source="dealls",
    )


def make_output() -> EnrichmentOutput:
    return EnrichmentOutput(
        skills=[EnrichedSkill(name="Python", confidence=0.9)],
        requirements=[
            EnrichedRequirement(
                type=RequirementType.EXPERIENCE,
                value="3 years backend experience",
                confidence=0.8,
            )
        ],
        confidence=0.85,
        warnings=[],
    )


def openai_status_error(error_cls, status_code: int):  # noqa: ANN001, ANN201
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(status_code, request=request)
    return error_cls("openai failed", response=response, body=None)


class FakeParser:
    def __init__(
        self,
        output: EnrichmentOutput | None = None,
        *,
        parsed: Any | None = None,
        exc: Exception | None = None,
    ) -> None:
        self.output = output
        self.parsed = parsed
        self.exc = exc
        self.calls: list[dict[str, Any]] = []

    async def parse(self, **kwargs: Any) -> ParsedCompletion:
        self.calls.append(kwargs)
        if self.exc is not None:
            raise self.exc
        parsed = self.output if self.parsed is None else self.parsed
        return ParsedCompletion(choices=[ParsedChoice(message=ParsedMessage(parsed=parsed))])


@dataclass
class ParsedCompletion:
    choices: list[ParsedChoice]


@dataclass
class ParsedChoice:
    message: ParsedMessage


@dataclass
class ParsedMessage:
    parsed: Any
    refusal: str | None = None
