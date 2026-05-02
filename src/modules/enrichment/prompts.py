from __future__ import annotations

from modules.enrichment.schemas import EnrichmentJobInput


def build_enrichment_messages(job: EnrichmentJobInput) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "Extract job skills and requirements only from the provided job text. "
                "Do not add facts that are not directly supported. "
                "Use low confidence when the text is vague. "
                "Return empty lists when evidence is missing."
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
            "Description:",
            description,
            "Requirements:",
            requirements,
        ]
    ).strip()
