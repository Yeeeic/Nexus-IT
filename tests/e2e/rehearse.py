r"""Start, test and remove a unique disposable NEXUS IT Compose stack.

Windows: .\.venv\Scripts\python.exe tests/e2e/rehearse.py --wsl Ubuntu
Add --keep-running for browser acceptance; then use --cleanup STATE_DIRECTORY.
No production .env, volume or enrolled device is accessed.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def protect(path: Path) -> None:
    if os.name == "nt":
        principal = os.environ["USERDOMAIN"] + "\\" + os.environ["USERNAME"]
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", principal + ":F", "*S-1-5-18:F"],
            check=True, capture_output=True, timeout=15)
    else:
        path.chmod(0o600)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wsl", help="Use this WSL distribution's Docker engine")
    parser.add_argument("--keep-running", action="store_true")
    parser.add_argument("--cleanup", type=Path)
    args = parser.parse_args()
    docker = ["wsl", "-d", args.wsl, "--", "docker"] if args.wsl else ["docker"]

    def engine_path(path: Path) -> str:
        if not args.wsl:
            return str(path)
        return "/mnt/" + path.drive[0].lower() + path.as_posix()[2:]

    if args.cleanup:
        state = args.cleanup.resolve()
        if state.parent != ROOT or not state.name.startswith(".pytest-e2e-"):
            raise SystemExit("Cleanup target must be a rehearsal directory directly inside the repository")
        manifest = json.loads((state / "manifest.json").read_text())
        project = manifest["project"]
        if not project.startswith("nexus-e2e-") or len(project) != 42:
            raise SystemExit("Invalid rehearsal project")
    else:
        for port in (18000, 18080):
            with socket.socket() as check:
                check.bind(("127.0.0.1", port))
        state = Path(tempfile.mkdtemp(prefix=".pytest-e2e-", dir=ROOT))
        project = "nexus-e2e-" + uuid4().hex
        key = Ed25519PrivateKey.generate()
        values = {
            name: secrets.token_hex(32) for name in (
                "NEXUS_POSTGRES_PASSWORD", "NEXUS_RUNTIME_POSTGRES_PASSWORD",
                "NEXUS_MAINTENANCE_POSTGRES_PASSWORD", "NEXUS_REDIS_PASSWORD",
                "NEXUS_SERVER_PEPPER", "NEXUS_SMTP_PASSWORD",
            )
        }
        values.update({
            "NEXUS_ENV": "development", "NEXUS_POSTGRES_DB": "nexus_it",
            "NEXUS_POSTGRES_USER": "nexus_bootstrap", "NEXUS_BIND_IP": "127.0.0.1",
            "NEXUS_ALLOWED_ORIGINS": "http://localhost:18080,http://127.0.0.1:18080",
            "NEXUS_ACTION_PRIVATE_KEY": base64.b64encode(key.private_bytes_raw()).decode(),
            "NEXUS_E2E_PUBLIC_KEY": base64.b64encode(key.public_key().public_bytes_raw()).decode(),
            "NEXUS_ACTION_KEY_VERSION": "1", "NEXUS_SMTP_HOST": "mail.invalid",
            "NEXUS_SMTP_USERNAME": "e2e@example.com", "NEXUS_SMTP_FROM": "e2e@example.com",
            "NEXUS_PASSWORD_RESET_URL": "https://localhost/reset-password",
            "NEXUS_SEED_ADMIN_EMAIL": "e2e@example.com",
            "NEXUS_SEED_ADMIN_PASSWORD": "E2e-" + secrets.token_hex(24),
        })
        (state / ".env").write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
        protect(state / ".env")
        (state / "manifest.json").write_text(json.dumps({"project": project}), encoding="utf-8")
    compose = docker + ["compose", "--project-name", project, "--env-file", engine_path(state / ".env"),
        "-f", engine_path(ROOT / "infra/compose.yaml"), "-f", engine_path(ROOT / "tests/e2e/compose.yaml")]
    sensitive = [line.split("=", 1)[1] for line in (state / ".env").read_text().splitlines()
                 if any(word in line.split("=", 1)[0] for word in ("PASSWORD", "PEPPER", "PRIVATE_KEY"))]

    def run(*command: str, timeout=360) -> str:
        environment = {key: value for key, value in os.environ.items() if not key.startswith("NEXUS_")}
        result = subprocess.run(compose + list(command), capture_output=True, text=True, env=environment,
            encoding="utf-8", errors="replace", timeout=timeout)
        output = result.stdout + result.stderr
        for secret in sensitive:
            output = output.replace(secret, "[REDACTED]")
        if result.returncode:
            raise RuntimeError(output[-6000:])
        return output

    def cleanup() -> None:
        run("down", "--volumes", "--remove-orphans")
        # The directory was created by this tool; validation above limits reused targets.
        shutil.rmtree(state)

    if args.cleanup:
        cleanup()
        print("Disposable rehearsal containers, volumes and credentials removed.")
        return
    try:
        run("config", "--quiet")
        print("Building isolated rehearsal images...", flush=True)
        run("build", "backend", "migrate", "seed-admin", "frontend", "e2e-runner", timeout=1200)
        print("Migrating disposable PostgreSQL and provisioning runtime...", flush=True)
        run("up", "-d", "--wait", "postgres", "redis")
        run("run", "--rm", "migrate")
        run("run", "--rm", "provision-runtime")
        run("run", "--rm", "seed-admin")
        run("up", "-d", "--wait", "backend", "frontend")
        print("Exercising real API and real agent...", flush=True)
        print(run("run", "--rm", "e2e-runner"), flush=True)
        (state / "result.json").write_text(json.dumps({"result": "PASS", "project": project}), encoding="utf-8")
    except BaseException:
        print(run("logs", "--tail", "35", "backend"), flush=True)
        cleanup()
        raise
    if args.keep_running:
        run("up", "-d", "e2e-browser-agent")
        print(f"Browser: http://localhost:18080\nPrivate credentials: {state / '.env'}\nCleanup state: {state}")
    else:
        cleanup()


if __name__ == "__main__":
    main()
