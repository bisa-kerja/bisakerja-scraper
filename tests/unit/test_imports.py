def test_core_packages_import() -> None:
    import api
    import config
    import core
    import integrations
    import jobs
    import modules
    import shared

    assert api is not None
    assert config is not None
    assert core is not None
    assert integrations is not None
    assert jobs is not None
    assert modules is not None
    assert shared is not None
