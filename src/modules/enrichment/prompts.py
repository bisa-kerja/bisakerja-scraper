from __future__ import annotations

from modules.enrichment.schemas import EnrichmentJobInput


def build_enrichment_messages(job: EnrichmentJobInput) -> list[dict[str, str]]:
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
                "Language rule: write requirements and warnings in natural Bahasa Indonesia. "
                "Output style rule: no emoji, no decorative symbols, no noisy icons. "
                "Output structure rule: requirement value should be one clear statement, "
                "not mixed multi-topic paragraph. "
                "Do not output English paraphrases unless text is copied "
                "verbatim from source evidence. "
                "Return schema-compliant structured output only."
            ),
        },
        {
            "role": "user",
            "content": build_user_prompt(job),
        },
    ]


def build_user_prompt(job: EnrichmentJobInput) -> str:
    description = job.description or ""
    requirements = job.requirements or ""
    return "\n".join(
        [
            f"Title: {job.title}",
            f"Company: {job.company}",
            f"Source: {job.source}",
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
            "- Requirement values and warnings must be written in natural Bahasa Indonesia.",
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
