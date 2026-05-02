from modules.enrichment import EnrichmentJobInput, build_enrichment_messages


def test_enrichment_prompt_uses_only_safe_job_fields() -> None:
    job = EnrichmentJobInput(
        title="Backend Engineer",
        description="Build APIs with Python.",
        requirements="3 years experience.",
        company="Bisakerja",
        source="dealls",
    )

    messages = build_enrichment_messages(job)
    combined = "\n".join(message["content"] for message in messages)

    assert "Backend Engineer" in combined
    assert "Build APIs with Python." in combined
    assert "raw_payload" not in combined
    assert "Authorization" not in combined
    assert "Bearer" not in combined
    assert "token" not in combined.casefold()
