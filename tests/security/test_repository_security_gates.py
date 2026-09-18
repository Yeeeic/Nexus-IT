"""Repository-level guards against committing credentials."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _tracked_files() -> set[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return {
        path.decode("utf-8").replace("\\", "/")
        for path in result.stdout.split(b"\0")
        if path
    }


def test_runtime_agent_config_is_not_tracked() -> None:
    assert "agent/agent_config.json" not in _tracked_files(), (
        "agent/agent_config.json is runtime state and must never be tracked; "
        "keep only agent/agent_config.example.json in Git"
    )


def test_pre_commit_uses_a_pinned_gitleaks_release() -> None:
    config = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")

    assert "repo: https://github.com/gitleaks/gitleaks" in config
    assert re.search(r"(?m)^\s+rev: v\d+\.\d+\.\d+\s*$", config)
    assert re.search(r"(?m)^\s+- id: gitleaks\s*$", config)


def test_gitleaks_extends_defaults_and_detects_nexus_agent_tokens() -> None:
    config = (ROOT / ".gitleaks.toml").read_text(encoding="utf-8")

    assert re.search(r"(?ms)^\[extend\].*?^useDefault\s*=\s*true\s*$", config)
    assert 'id = "nexus-agent-token"' in config


def test_ci_scans_full_history_and_audits_frontend_dependencies() -> None:
    workflow = (ROOT / ".github/workflows/security.yml").read_text(encoding="utf-8")

    assert "fetch-depth: 0" in workflow
    assert re.search(
        r"working-directory:\s*\./frontend\s+run:\s*npm audit --audit-level=high",
        workflow,
    )
