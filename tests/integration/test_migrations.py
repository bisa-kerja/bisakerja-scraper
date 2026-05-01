from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_initial_migration_upgrade_and_downgrade(tmp_path) -> None:
    database_path = tmp_path / "migration.sqlite"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database_path}")

    assert {"scrape_runs", "raw_jobs", "normalized_jobs", "sync_events"} <= set(
        inspect(engine).get_table_names()
    )

    command.downgrade(config, "base")

    assert "scrape_runs" not in inspect(engine).get_table_names()
