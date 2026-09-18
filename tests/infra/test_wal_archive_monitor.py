"""Exercise the monitor against disposable PostgreSQL, never the project database."""

from __future__ import annotations

import os
import subprocess
import time
import uuid
from pathlib import Path

import pytest

from tests.infra.conftest import _docker_command


pytestmark = pytest.mark.skipif(
    os.getenv("NEXUS_RUN_WAL_TESTS") != "1",
    reason="set NEXUS_RUN_WAL_TESTS=1 for isolated PostgreSQL WAL tests",
)
SCRIPT = Path(__file__).resolve().parents[2] / "infra/postgres/pitr-check-archive-lag.sh"
IMAGE = "postgres:16.15-bookworm@sha256:60f4761b9035e0b8d5218f701a8c3382f641bf12b1604822574cf5be3baeb537"


@pytest.fixture
def database():
    docker, _ = _docker_command()
    name = "nexus-wal-monitor-test-" + uuid.uuid4().hex

    def run(*args, input=None, check=True):
        return subprocess.run(
            [*docker, *args], input=input, text=True, capture_output=True,
            check=check, timeout=45,
        )

    run("run", "-d", "--name", name, "--network", "none",
        "--tmpfs", "/var/lib/postgresql/data",
        "-e", "POSTGRES_HOST_AUTH_METHOD=trust", IMAGE,
        "postgres", "-c", "archive_mode=on", "-c", "archive_timeout=60",
        "-c", "archive_command=test -f /tmp/archive-enabled")
    try:
        for _ in range(60):
            if run("exec", name, "pg_isready", "-U", "postgres", check=False).returncode == 0:
                break
            time.sleep(0.25)
        else:
            pytest.fail("Isolated PostgreSQL did not become ready")

        def sql(query):
            return run("exec", name, "psql", "-U", "postgres", "-AtX",
                       "-v", "ON_ERROR_STOP=1", "-c", query).stdout.strip()

        def monitor(**environment):
            command = ["exec", "-i", "-e", "NEXUS_POSTGRES_HOST=127.0.0.1",
                       "-e", "NEXUS_POSTGRES_USER=postgres",
                       "-e", "NEXUS_POSTGRES_PASSWORD=isolated-test"]
            for key, value in environment.items():
                command.extend(["-e", f"{key}={value}"])
            # Windows text-mode pipes translate LF to CRLF before WSL receives it.
            return run(*command, name, "bash", "-c", "tr -d '\\r' | bash",
                       input=SCRIPT.read_text(encoding="utf-8"), check=False)

        yield run, name, sql, monitor
    finally:
        # Exact unique container, tmpfs only; no application volumes are mounted.
        run("rm", "-fv", name, check=False)


def test_idle_database_does_not_alert_after_old_success(database):
    run, name, sql, monitor = database
    run("exec", name, "touch", "/tmp/archive-enabled")
    sql("CREATE TABLE probe (id integer); INSERT INTO probe VALUES (1);")
    sql("SELECT pg_switch_wal();")
    for _ in range(60):
        if int(sql("SELECT archived_count FROM pg_stat_archiver")) > 0:
            break
        time.sleep(0.25)
    else:
        pytest.fail("Test WAL was not archived")
    time.sleep(2.1)
    result = monitor(NEXUS_WAL_WARNING_SECONDS="1", NEXUS_WAL_CRITICAL_SECONDS="2")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "lag 0s" in result.stdout


@pytest.mark.parametrize("age, status", [(650, 1), (1200, 2)])
def test_old_pending_wal_alerts_even_with_recent_failure(database, age, status):
    run, name, sql, monitor = database
    sql("CREATE TABLE probe (id integer); INSERT INTO probe VALUES (1);")
    sql("SELECT pg_switch_wal();")
    for _ in range(60):
        if int(sql("SELECT failed_count FROM pg_stat_archiver")) > 0:
            break
        time.sleep(0.25)
    else:
        pytest.fail("Archive failure was not observed")
    run("exec", name, "bash", "-ceu",
        f"touch -d '{age} seconds ago' /var/lib/postgresql/data/pg_wal/archive_status/*.ready")
    result = monitor()
    assert result.returncode == status, result.stdout + result.stderr


def test_database_error_is_critical_not_warning(database):
    _, _, _, monitor = database
    result = monitor(NEXUS_POSTGRES_DB="missing_database")
    assert result.returncode == 2, result.stdout + result.stderr
