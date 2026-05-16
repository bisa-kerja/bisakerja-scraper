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
    assert "output language: english" in combined.casefold()
    assert "output generated/paraphrased text in english only" in combined.casefold()
    assert "never use indonesian function words" in combined.casefold()
    assert "if evidence exists, do not return empty output" in combined.casefold()
    assert (
        "if requirement evidence exists, return at least one requirement item"
        in combined.casefold()
    )
    assert "if skill evidence exists, return at least one skill item" in combined.casefold()
    assert (
        "if only role-level evidence is available, still return one conservative requirement"
        in combined.casefold()
    )
    assert "task:" in combined.casefold()
    assert "raw_payload" not in combined
    assert "Authorization" not in combined
    assert "Bearer" not in combined
    assert "token" not in combined.casefold()


def test_enrichment_prompt_can_target_english_output() -> None:
    job = EnrichmentJobInput(
        title="Backend Engineer",
        description="Build APIs with Python.",
        requirements="3 years experience.",
        company="Bisakerja",
        source="dealls",
    )

    messages = build_enrichment_messages(job, output_language="english")
    combined = "\n".join(message["content"] for message in messages)

    assert "Output language: English" in combined
    assert "natural English" in combined
    assert "Translate Indonesian or mixed-language source evidence" in combined
    assert "never emit Indonesian function words" in combined
