"""Static contract tests for portable agent installers."""

import ipaddress
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_installers_do_not_embed_a_deployment_ip() -> None:
    for relative_path in (
        "frontend/public/install-agent.ps1",
        "frontend/public/install-agent.sh",
    ):
        text = _read(relative_path)
        for host in re.findall(r"https?://([^/:\s]+)", text, re.IGNORECASE):
            try:
                address = ipaddress.ip_address(host.strip("[]"))
            except ValueError:
                continue
            assert address.is_loopback, f"{relative_path} embeds deployment IP {address}"


def test_windows_installer_requires_public_keys_and_uses_configured_artifact_origin() -> None:
    script = _read("frontend/public/install-agent.ps1")

    assert "$PublicKeysJson" in script
    assert "ConvertFrom-Json" in script
    assert "$ArtifactBaseUrl" in script
    assert '"Xf/xgyY5mbRg9YWMkARqI3Qq1+rvZF/PHx1kcwpD+60="' not in script


def test_linux_installer_passes_public_keys_to_agent_service() -> None:
    script = _read("frontend/public/install-agent.sh")

    assert "PUBLIC_KEYS_JSON" in script
    assert "NEXUS_AGENT_PUBLIC_KEYS" in script
    assert "ARTIFACT_BASE_URL" in script


def test_quick_installer_requires_key_material_in_generated_commands() -> None:
    component = _read("frontend/src/views/devices/QuickInstallerModal.tsx")

    assert "PUBLIC_KEYS_JSON" in component
    assert "PublicKeysJson" in component
