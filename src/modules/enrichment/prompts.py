from __future__ import annotations

from modules.enrichment.schemas import EnrichmentJobInput


def build_enrichment_messages(
    job: EnrichmentJobInput,
    *,
    output_language: str = "indonesian",
) -> list[dict[str, str]]:
    language = _normalize_output_language(output_language)
    language_name = "English" if language == "english" else "Bahasa Indonesia"
    natural_language = "natural English" if language == "english" else "natural Bahasa Indonesia"
    source_language_rule = (
        "Do not output Indonesian paraphrases unless text is copied verbatim from source evidence."
        if language == "english"
        else (
            "Do not output English paraphrases unless text is copied verbatim from source evidence."
        )
    )
    return [
        {
            "role": "system",
            "content": (
                "Extract job skills and requirements only from the provided text evidence. "
                "Do not add unsupported facts. "
                "If evidence exists, do not return empty output. "
                "If requirement evidence exists, return at least one requirement item. "
                "If skill evidence exists, return at least one skill item. "
                "Evidence priority: requirements > description > title. "
                "If only role-level evidence is available, "
                "still return one conservative requirement "
                "and one conservative skill derived from role context. "
                "Parse both sentences and bullet-like fragments as valid evidence. "
                "Treat responsibilities, qualifications, and requirement headings "
                "as requirement evidence. "
                "Skills must be specific (technology, tools, domain skills) "
                "and deduplicated case-insensitively. "
                "When skills are implied by explicit requirement text "
                "(for example Python, SQL, Docker), "
                "extract them as skills with conservative confidence. "
                "Requirements must be atomic, concise, and typed as "
                "SKILL, EXPERIENCE, EDUCATION, or OTHER. "
                "When evidence is weak, lower confidence instead of guessing. "
                f"Language rule: write requirements and warnings in {natural_language}. "
                f"Output language must be {language_name}. "
                "Output style rule: no emoji, no decorative symbols, no noisy icons. "
                "Output structure rule: requirement value should be one clear statement, "
                "not mixed multi-topic paragraph. "
                f"{source_language_rule} "
                "Return schema-compliant structured output only."
            ),
        },
        {
            "role": "user",
            "content": build_user_prompt(job, output_language=language),
        },
    ]


def build_user_prompt(job: EnrichmentJobInput, *, output_language: str = "indonesian") -> str:
    language = _normalize_output_language(output_language)
    language_name = "English" if language == "english" else "Bahasa Indonesia"
    natural_language = "natural English" if language == "english" else "natural Bahasa Indonesia"
    description = job.description or ""
    requirements = job.requirements or ""
    return "\n".join(
        [
            f"Title: {job.title}",
            f"Company: {job.company}",
            f"Source: {job.source}",
            f"Output language: {language_name}",
            "Task:",
            "- Extract at least one requirement when requirement/description evidence exists.",
            "- Extract at least one skill when explicit skill evidence exists.",
            (
                "- If only role context exists, return one conservative requirement "
                "and one role-level skill."
            ),
            "- Extract skills that are explicitly stated or strongly supported by the text.",
            (
                "- If requirement sentences contain explicit technologies/tools, "
                "also emit them as skill items."
            ),
            f"- Requirement values and warnings must be written in {natural_language}.",
            "- Keep each requirement focused on one qualification or competency only.",
            "- Do not include emoji, icons, or decorative symbols in values.",
            "- Keep technology names and proper nouns as in source text.",
            "- Never include information that is not present in the text.",
            "Description:",
            description,
            "Requirements:",
            requirements,
        ]
    ).strip()


def _normalize_output_language(value: str) -> str:
    language = (value or "indonesian").strip().casefold()
    if language not in {"indonesian", "english"}:
        raise ValueError("output_language must be indonesian or english")
    return language
