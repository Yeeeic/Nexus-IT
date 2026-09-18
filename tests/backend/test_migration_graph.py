from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_minimum_privilege_repair_migration_is_current_head() -> None:
    config = Config(REPOSITORY_ROOT / "backend" / "alembic.ini")
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_current_head() == "20260831_0024"
