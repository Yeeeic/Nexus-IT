import os
import shutil
import subprocess
from pathlib import Path
import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPOSITORY_ROOT / "infra" / "compose.yaml"
ENV_FILE = REPOSITORY_ROOT / ".env"

_DOCKER_CMD_CACHE: tuple[list[str], bool] | None = None


def _docker_command() -> tuple[list[str], bool]:
    global _DOCKER_CMD_CACHE
    if _DOCKER_CMD_CACHE is not None:
        return _DOCKER_CMD_CACHE

    wsl_command = shutil.which("wsl")
    if wsl_command is not None:
        for _ in range(2):
            try:
                completed = subprocess.run(
                    [wsl_command, "-d", "Ubuntu", "--", "docker", "ps"],
                    capture_output=True,
                    stdin=subprocess.DEVNULL,
                    check=False,
                    text=True,
                    timeout=30,
                )
                if completed.returncode == 0:
                    _DOCKER_CMD_CACHE = ([wsl_command, "-d", "Ubuntu", "--", "docker"], True)
                    return _DOCKER_CMD_CACHE
            except (subprocess.TimeoutExpired, OSError):
                pass

    command = shutil.which("docker")
    if command is not None:
        try:
            completed = subprocess.run(
                [command, "ps"],
                capture_output=True,
                stdin=subprocess.DEVNULL,
                check=False,
                text=True,
                timeout=5,
            )
            if completed.returncode == 0:
                _DOCKER_CMD_CACHE = ([command], False)
                return _DOCKER_CMD_CACHE
        except (subprocess.TimeoutExpired, OSError):
            pass

    pytest.fail("Working Docker daemon is required for database integration tests")


def _wsl_path(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    return f"/mnt/{drive}{resolved.as_posix()[len(resolved.drive):]}"


def _run_sql(sql: str) -> list[str]:
    cmd_prefix, is_wsl = _docker_command()
    env_str = _wsl_path(ENV_FILE) if is_wsl else str(ENV_FILE)
    compose_str = _wsl_path(COMPOSE_FILE) if is_wsl else str(COMPOSE_FILE)
    command = [
        *cmd_prefix,
        "compose",
        "--env-file",
        env_str,
        "--file",
        compose_str,
        "exec",
        "-T",
        "postgres",
        "psql",
        "--username",
        "nexus_bootstrap",
        "--dbname",
        "nexus_it",
        "--no-psqlrc",
        "--tuples-only",
        "--no-align",
        "--set",
        "ON_ERROR_STOP=1",
    ]
    completed = subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        input=sql,
        capture_output=True,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        pytest.fail(f"PostgreSQL test command failed:\n{completed.stderr}")
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


@pytest.fixture(scope="session", autouse=True)
def ensure_postgres_running() -> None:
    if os.getenv("NEXUS_RUN_DB_TESTS") != "1":
        return
    cmd_prefix, is_wsl = _docker_command()
    env_str = _wsl_path(ENV_FILE) if is_wsl else str(ENV_FILE)
    compose_str = _wsl_path(COMPOSE_FILE) if is_wsl else str(COMPOSE_FILE)
    subprocess.run(
        [*cmd_prefix, "compose", "--env-file", env_str, "--file", compose_str, "up", "-d", "postgres"],
        check=True,
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )
