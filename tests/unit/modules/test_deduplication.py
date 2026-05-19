from modules.deduplication import (
    DedupAction,
    DedupCandidate,
    DedupEngine,
    DedupReason,
    make_fallback_fingerprint,
    resolve_source_identity,
)


def candidate(
    *,
    source_platform: str = "dealls",
    external_id: str | None = "job-1",
    source_slug: str | None = "software-engineer",
    title: str = "Software Engineer",
    company_name: str = "Bisakerja",
) -> DedupCandidate:
    identity = resolve_source_identity(
        source_platform=source_platform,
        external_id=external_id,
        source_slug=source_slug,
        title=title,
        company_name=company_name,
        source_url=f"https://example.test/{source_slug or title}",
    )
    return DedupCandidate(
        identity=identity,
        title=title,
        company_name=company_name,
        source_url=f"https://example.test/{source_slug or title}",
    )


def test_dedup_engine_updates_duplicate_identity_instead_of_inserting() -> None:
    engine = DedupEngine()

    first = engine.evaluate(candidate())
    duplicate = engine.evaluate(candidate())

    assert first.action is DedupAction.INSERT
    assert duplicate.action is DedupAction.UPDATE
    assert duplicate.reason is DedupReason.DUPLICATE_IDENTITY
    assert duplicate.dedup_reason == "duplicate_identity"


def test_source_platform_separates_same_external_id() -> None:
    engine = DedupEngine()

    dealls = engine.evaluate(candidate(source_platform="dealls", external_id="123"))
    glints = engine.evaluate(candidate(source_platform="glints", external_id="123"))

    assert dealls.action is DedupAction.INSERT
    assert glints.action is DedupAction.INSERT
    assert dealls.identity.key != glints.identity.key


def test_missing_identity_without_fallback_is_quarantined() -> None:
    identity = resolve_source_identity(source_platform="dealls")
    decision = DedupEngine().evaluate(DedupCandidate(identity=identity))

    assert decision.action is DedupAction.QUARANTINE
    assert decision.reason is DedupReason.MISSING_IDENTITY


def test_fallback_fingerprint_used_when_external_id_missing() -> None:
    engine = DedupEngine()
    fallback = candidate(external_id=None)

    decision = engine.evaluate(fallback)

    assert decision.action is DedupAction.INSERT
    assert decision.reason is DedupReason.FALLBACK_FINGERPRINT
    assert fallback.identity.uses_fallback is True
    assert fallback.identity.fingerprint == make_fallback_fingerprint(
        source_platform="dealls",
        source_slug="software-engineer",
        title="Software Engineer",
        company_name="Bisakerja",
        source_url="https://example.test/software-engineer",
    )


def test_slug_drift_is_recorded() -> None:
    engine = DedupEngine()
    engine.evaluate(candidate(source_slug="old-slug"))

    decision = engine.evaluate(candidate(source_slug="new-slug"))

    assert decision.action is DedupAction.UPDATE
    assert decision.reason is DedupReason.SLUG_DRIFT


def test_identity_collision_is_recorded() -> None:
    engine = DedupEngine()
    engine.evaluate(candidate(source_slug="old-slug", title="Engineer", company_name="A"))

    decision = engine.evaluate(
        candidate(source_slug="new-slug", title="Designer", company_name="B")
    )

    assert decision.action is DedupAction.UPDATE
    assert decision.reason is DedupReason.IDENTITY_COLLISION
