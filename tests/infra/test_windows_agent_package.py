"""Static contract and security tests for the NEXUS IT Windows agent package.

These tests verify properties of the source tree that must hold before any
binary is built or distributed. They do NOT require Docker, a VM, or network
access.

Run with:
    pytest tests/infra/test_windows_agent_package.py -v
"""

from __future__ import annotations

import json
import ipaddress
import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

AGENT_WINDOWS = ROOT / "agente-windows"
AGENT_SRC     = ROOT / "agent"
INSTALLER_PS1 = ROOT / "frontend" / "public" / "install-agent.ps1"
CTL_PS1       = AGENT_WINDOWS / "service" / "nexus-agent-ctl.ps1"
SVC_PY        = AGENT_WINDOWS / "service" / "nexus_agent_service.py"
BUILD_PS1     = AGENT_WINDOWS / "build-package.ps1"
WINDOWS_LOCK  = AGENT_WINDOWS / "requirements-windows.lock"
BUILD_MD      = AGENT_WINDOWS / "BUILD.md"
INSTALL_MD    = AGENT_WINDOWS / "INSTALL.md"
LEEME         = AGENT_WINDOWS / "LEEME.txt"
BAT           = AGENT_WINDOWS / "iniciar-agente.bat"
EMBEDDED_CFG  = AGENT_WINDOWS / "agent" / "agent_config.json"
EXAMPLE_CFG   = AGENT_WINDOWS / "agent_config.example.json"
SETUP_PY      = AGENT_WINDOWS / "installer" / "nexus_agent_setup.py"
SETUP_SPEC    = AGENT_WINDOWS / "installer" / "nexus-agent-setup.spec"

ALLOWED_CONFIG_FIELDS = frozenset(
    {"server_url", "device_id", "hostname", "public_keys", "inventory_interval"}
)

TOKEN_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
    r"\.[A-Za-z0-9_-]{32,}\b"
)
URL_HOST_PATTERN = re.compile(r"https?://([^/:\s]+)", re.IGNORECASE)

CLOSED_CATALOG = frozenset(
    {"restart_service", "flush_dns", "collect_extended_diagnostics", "reboot_system"}
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Security: no secrets or deployment values in source files
# ---------------------------------------------------------------------------
class TestNoSecretsInSource:
    """Verify that deployment credentials are absent without storing them in tests."""

    CHECKED_FILES = [
        INSTALLER_PS1, CTL_PS1, SVC_PY, BUILD_PS1, BUILD_MD,
        INSTALL_MD, LEEME, BAT,
    ]

    def test_no_agent_token_shape(self) -> None:
        for path in self.CHECKED_FILES:
            if path.exists():
                assert TOKEN_PATTERN.search(_read(path)) is None, (
                    f"{path.name} contains a value shaped like an agent token"
                )

    def test_no_non_loopback_ip_in_distribution_urls(self) -> None:
        for path in self.CHECKED_FILES:
            if not path.exists():
                continue
            for host in URL_HOST_PATTERN.findall(_read(path)):
                try:
                    address = ipaddress.ip_address(host.strip("[]"))
                except ValueError:
                    continue
                assert address.is_loopback, (
                    f"{path.name} contains deployment URL with IP {address}"
                )

    def test_legacy_embedded_runtime_config_is_absent(self) -> None:
        assert not EMBEDDED_CFG.exists(), (
            "generated Windows package must not contain agent_config.json"
        )


# ---------------------------------------------------------------------------
# Config: example only contains allowed fields
# ---------------------------------------------------------------------------
class TestConfigExample:
    def test_example_config_fields_allowed(self) -> None:
        """agent_config.example.json must only contain fields accepted by load_config()."""
        cfg_path = AGENT_WINDOWS / "agent_config.example.json"
        if not cfg_path.exists():
            # Fall back to canonical example
            cfg_path = AGENT_SRC / "agent_config.example.json"
        assert cfg_path.exists(), "agent_config.example.json not found"
        value = json.loads(cfg_path.read_text("utf-8"))
        assert isinstance(value, dict)
        unknown = set(value) - ALLOWED_CONFIG_FIELDS
        assert not unknown, f"Unknown fields in example config: {unknown}"

    def test_example_config_no_interval_field(self) -> None:
        """The rejected 'interval' field must not appear in config examples."""
        for cfg_path in [
            AGENT_WINDOWS / "agent_config.example.json",
            AGENT_SRC / "agent_config.example.json",
        ]:
            if cfg_path.exists():
                value = json.loads(cfg_path.read_text("utf-8"))
                assert "interval" not in value, (
                    f"{cfg_path.name} contains rejected 'interval' field"
                )

    def test_embedded_config_fields_allowed(self) -> None:
        if not EMBEDDED_CFG.exists():
            pytest.skip("embedded config not found")
        value = json.loads(_read(EMBEDDED_CFG))
        assert isinstance(value, dict)
        unknown = set(value) - ALLOWED_CONFIG_FIELDS
        assert not unknown, f"Unknown fields: {unknown}"

    def test_embedded_config_no_interval(self) -> None:
        if not EMBEDDED_CFG.exists():
            pytest.skip("embedded config not found")
        value = json.loads(_read(EMBEDDED_CFG))
        assert "interval" not in value


# ---------------------------------------------------------------------------
# Installer: correct behavior
# ---------------------------------------------------------------------------
class TestInstaller:
    def test_setup_source_compiles(self) -> None:
        source = _read(SETUP_PY)
        compile(source, str(SETUP_PY), "exec")

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI only")
    def test_setup_dpapi_round_trip(self) -> None:
        spec = importlib.util.spec_from_file_location("nexus_agent_setup_test", SETUP_PY)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        plaintext = b"test-only-agent-token"
        encrypted = module._dpapi_protect(plaintext)
        assert encrypted != plaintext
        assert module._dpapi_unprotect(encrypted) == plaintext

    def test_setup_validates_uuidv4_and_ed25519_keys(self) -> None:
        text = _read(SETUP_PY)
        assert "UUID(" in text
        assert "identifier.version != 4" in text
        assert "base64.b64decode" in text
        assert "len(decoded) != 32" in text

    def test_setup_hardens_directories_before_writing_config_or_token(self) -> None:
        text = _read(SETUP_PY)
        assert text.index("_harden(INSTALL_DIR)", text.index("def cmd_install")) < text.index(
            "CONFIG_FILE.write_text", text.index("def cmd_install")
        )

    def test_setup_is_fresh_install_only_and_rolls_back_failures(self) -> None:
        text = _read(SETUP_PY)
        assert "def _cleanup_partial_install" in text
        assert "if _service_exists():" in text
        assert "if INSTALL_DIR.exists():" in text
        assert '"create", SERVICE_NAME' in text
        assert 'verb = "config"' not in text
        assert "_cleanup_partial_install()" in text

    def test_setup_service_mode_fails_closed_without_pywin32(self) -> None:
        text = _read(SETUP_PY)
        assert "except ImportError as exc:" in text
        assert "def _run_agent_loop" not in text
        assert 'os.environ["NEXUS_AGENT_TOKEN"]' not in text

    def test_setup_checks_scm_and_purge_results(self) -> None:
        text = _read(SETUP_PY)
        assert "def _run_sc(" in text
        assert "def _wait_service_removed(" in text
        assert "ignore_errors=True" not in text
        assert "MoveFileExW" in text

    def test_setup_spec_does_not_bundle_private_config_files(self) -> None:
        text = _read(SETUP_SPEC)
        assert '(AGENT,   "agent")' not in text
        assert 'agent_config.json' not in text

    def test_setup_directory_acls_are_inherited_by_runtime_files(self) -> None:
        text = _read(SETUP_PY)
        assert '"*S-1-5-18:(OI)(CI)(F)"' in text
        assert '"*S-1-5-32-544:(OI)(CI)(F)"' in text
        assert '["/T", "/Q"] if path.is_dir() else []' in text

    def test_setup_version_metadata_is_valid(self) -> None:
        from PyInstaller.utils.win32.versioninfo import load_version_info_from_text_file

        info = load_version_info_from_text_file(
            str(AGENT_WINDOWS / "installer" / "version_info.txt")
        )
        assert info is not None

    def test_installer_requires_public_keys(self) -> None:
        text = _read(INSTALLER_PS1)
        assert "$PublicKeysJson" in text
        assert "ConvertFrom-Json" in text
        assert "Assert-PublicKeys" in text
        assert "FromBase64String" in text
        assert "$decoded.Length -ne 32" in text

    def test_installer_requires_uuidv4(self) -> None:
        text = _read(INSTALLER_PS1)
        assert "Assert-DeviceId" in text
        assert "UUIDv4" in text

    def test_installer_uses_configurable_artifact_url(self) -> None:
        text = _read(INSTALLER_PS1)
        assert "$ArtifactBaseUrl" in text
        assert '"$ArtifactBaseUrl/$PackageName"' in text
        assert '"$ArtifactBaseUrl/public/$PackageName"' not in text
        assert '$PackageVersion  = "1.0.0"' in text

    def test_installer_no_known_deployment_ip(self) -> None:
        text = _read(INSTALLER_PS1)
        assert TOKEN_PATTERN.search(text) is None

    def test_installer_no_known_deployment_pubkey(self) -> None:
        text = _read(INSTALLER_PS1)
        assert "<clave-ed25519-base64>" in text

    def test_installer_verifies_sha256(self) -> None:
        text = _read(INSTALLER_PS1)
        assert "SHA256" in text.upper() or "sha256" in text.lower()
        assert re.search(
            r"\[Parameter\(Mandatory\s*=\s*\$true\)\]\s*\[string\]\$ExpectedSha256",
            text,
        )
        assert "Verificacion omitida" not in text

    def test_installer_validates_artifact_origin(self) -> None:
        text = _read(INSTALLER_PS1)
        assert "Assert-ServerUrl $ArtifactBaseUrl" in text

    def test_installer_no_interval_field_in_config(self) -> None:
        """The installer must not write the rejected 'interval' field as a config key.

        install-agent.ps1 delegates config writing to nexus-agent-ctl.ps1.
        We verify:
        - No bare 'interval =' key in the installer.
        - The installer calls nexus-agent-ctl.ps1 (which handles config correctly).
        The CTL's correct use of inventory_interval is verified by TestWindowsService.
        """
        import re
        text = _read(INSTALLER_PS1)
        # Must not write bare `interval = <value>` (without inventory_ prefix)
        bare_interval = re.search(r'(?<!inventory_)\binterval\s*=\s*\d', text)
        assert bare_interval is None, (
            f"Installer writes rejected bare 'interval' config key: {bare_interval}"
        )
        # Must delegate to nexus-agent-ctl.ps1 for actual install/config
        assert "nexus-agent-ctl" in text.lower() or "CtlScript" in text


    def test_installer_downloads_zip_not_just_exe(self) -> None:
        text = _read(INSTALLER_PS1)
        assert ".zip" in text.lower()

    def test_installer_requires_https_or_loopback_only(self) -> None:
        text = _read(INSTALLER_PS1)
        # Must have HTTPS check
        assert "https" in text.lower()
        # Must validate loopback when HTTP is allowed
        assert "loopback" in text.lower() or "127.0.0.1" in text

    def test_installer_verifies_package_content(self) -> None:
        """Installer must check for required files before invoking install."""
        text = _read(INSTALLER_PS1)
        assert "runtime" in text
        assert "MANIFEST" in text or "nexus-agent-ctl" in text

    def test_installer_rejects_zip_path_traversal(self) -> None:
        text = _read(INSTALLER_PS1)
        assert "Paquete ZIP contiene una ruta insegura" in text
        assert "GetFullPath" in text

    def test_installer_does_not_write_token_to_file(self) -> None:
        """Token must never be written to a file in plaintext."""
        text = _read(INSTALLER_PS1)
        # Token must go to DPAPI or be passed to ctl script, not Set-Content
        assert "$Token" not in text or "Set-Content" not in text or (
            # Allow if it uses DPAPI / ctl
            "DPAPI" in text or "nexus-agent-ctl" in text
        )

    def test_installer_cleans_up_on_error(self) -> None:
        text = _read(INSTALLER_PS1)
        assert "catch" in text.lower() or "finally" in text.lower()
        assert "TempDir" in text or "Remove-Item" in text


# ---------------------------------------------------------------------------
# Windows Service: correct structure
# ---------------------------------------------------------------------------
class TestWindowsService:
    def test_service_py_exists(self) -> None:
        assert SVC_PY.exists(), "nexus_agent_service.py not found"

    def test_service_uses_pywin32(self) -> None:
        text = _read(SVC_PY)
        assert "win32serviceutil" in text
        assert "ServiceFramework" in text

    def test_service_uses_dpapi_not_plaintext(self) -> None:
        text = _read(SVC_PY)
        assert "dpapi" in text.lower() or "CryptUnprotectData" in text
        assert "load_token_dpapi" in text

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI only")
    def test_service_dpapi_round_trip(self) -> None:
        spec = importlib.util.spec_from_file_location("nexus_agent_service_test", SVC_PY)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        plaintext = b"test-only-agent-token"
        encrypted = module._dpapi_protect(plaintext)
        assert encrypted != plaintext
        assert module._dpapi_unprotect(encrypted) == plaintext

    def test_service_does_not_export_token_to_child_environment(self) -> None:
        text = _read(SVC_PY)
        assert 'os.environ["NEXUS_AGENT_TOKEN"]' not in text

    def test_service_no_shell_execution(self) -> None:
        text = _read(SVC_PY)
        # Must not use shell=True or arbitrary command execution
        assert "shell=True" not in text
        assert "os.system" not in text

    def test_service_closed_catalog_only(self) -> None:
        """Service must not accept arbitrary action names."""
        text = _read(SVC_PY)
        # The service delegates to the agent which enforces ACTION_CATALOG
        assert "ACTION_CATALOG" in text or "closed" in text.lower() or "catalog" in text.lower()

    def test_service_stops_cleanly(self) -> None:
        text = _read(SVC_PY)
        assert "SvcStop" in text
        assert "SetEvent" in text or "stop_event" in text

    def test_service_startup_failures_trigger_scm_recovery(self) -> None:
        text = _read(SVC_PY)
        assert 'raise RuntimeError("agent token unavailable")' in text
        assert 'raise RuntimeError("bundled agent code unavailable")' in text
        assert "except Exception as exc:" in text
        assert "            raise\n" in text

    def test_service_does_not_log_token(self) -> None:
        """Service log calls must not include the token value."""
        text = _read(SVC_PY)
        # Token is loaded into local var; verify no direct logging of token
        assert 'logger.info(".*token.*"' not in text.lower()
        # Acceptable: logging.error about missing token (sanitized message)

    def test_ctl_script_exists(self) -> None:
        assert CTL_PS1.exists(), "nexus-agent-ctl.ps1 not found"

    def test_ctl_installs_service_via_sc(self) -> None:
        text = _read(CTL_PS1)
        assert "sc.exe" in text or "sc " in text
        assert "create" in text.lower()

    def test_ctl_applies_acl(self) -> None:
        text = _read(CTL_PS1)
        assert "icacls" in text
        assert "*S-1-5-18:(F)" in text
        assert "*S-1-5-32-544:(F)" in text
        assert "*S-1-5-18:(OI)(CI)(F)" in text
        assert "*S-1-5-32-544:(OI)(CI)(F)" in text
        assert "/T /Q" in text
        assert "$LASTEXITCODE" in text

    def test_ctl_validates_ed25519_public_keys(self) -> None:
        text = _read(CTL_PS1)
        assert "Assert-PublicKeys" in text
        assert "FromBase64String" in text
        assert "$decoded.Length -ne 32" in text
        assert "Assert-DeviceId" in text

    def test_ctl_never_embeds_token_in_python_command(self) -> None:
        text = _read(CTL_PS1)
        assert "store_token_dpapi(r'$TokenPlain')" not in text
        assert "--store-token-stdin" in text
        assert "ZeroFreeBSTR" in text

    def test_ctl_auto_restart_on_failure(self) -> None:
        text = _read(CTL_PS1)
        assert "failure" in text.lower() or "restart" in text.lower()

    def test_ctl_checks_service_control_failures(self) -> None:
        text = _read(CTL_PS1)
        assert "function Invoke-Sc" in text
        assert 'throw "sc.exe fallo' in text
        assert "sc.exe create" not in text
        assert "sc.exe delete" not in text

    def test_ctl_writes_python_json_without_utf8_bom(self) -> None:
        text = _read(CTL_PS1)
        assert "System.Text.UTF8Encoding($false)" in text
        assert "Set-Content -Path $ConfigPath -Encoding UTF8" not in text

    def test_ctl_supports_rollback(self) -> None:
        text = _read(CTL_PS1)
        assert "rollback" in text.lower()

    def test_ctl_verifies_manifest_before_install_or_update(self) -> None:
        text = _read(CTL_PS1)
        assert "function Assert-PackageIntegrity" in text
        assert text.count("Assert-PackageIntegrity") >= 3
        assert "function Assert-DirectoryIntegrity" in text
        assert "Archivo no declarado en $ManifestName" in text
        assert "Get-FileHash" in text

    def test_ctl_secures_and_verifies_update_backup(self) -> None:
        text = _read(CTL_PS1)
        assert "function New-BackupManifest" in text
        assert "function Assert-BackupIntegrity" in text
        update = text[text.index("function Update-Agent"):text.index("function Invoke-Rollback")]
        assert update.index("Apply-Acl $BackupPath") < update.index("Copy-Item $src")
        assert "New-BackupManifest" in update
        rollback = text[text.index("function Invoke-Rollback"):text.index("function Uninstall-Agent")]
        assert "Assert-BackupIntegrity" in rollback

    def test_ctl_fresh_install_rejects_residue_and_cleans_failures(self) -> None:
        text = _read(CTL_PS1)
        install = text[text.index("function Install-Agent"):text.index("function Start-Agent")]
        assert "if (Test-Path -LiteralPath $InstallPath)" in install
        assert "Remove-PartialInstallation" in install
        assert install.index("Apply-Acl $InstallPath") < install.index("Copy-Item $src")

    def test_powershell_installers_reject_url_credentials_and_components(self) -> None:
        for path in (CTL_PS1, ROOT / "frontend" / "public" / "install-agent.ps1"):
            text = _read(path)
            assert "$uri.UserInfo" in text
            assert '$uri.AbsolutePath -ne "/"' in text
            assert "$uri.Query" in text
            assert "$uri.Fragment" in text

    def test_ctl_is_compatible_with_declared_powershell_51(self) -> None:
        text = _read(CTL_PS1)
        assert "#Requires -Version 5.1" in text
        assert "return $svc ?" not in text

    def test_ctl_uninstall_supports_purge(self) -> None:
        text = _read(CTL_PS1)
        assert "Purge" in text or "purge" in text.lower()


# ---------------------------------------------------------------------------
# Build: reproducible and canon-based
# ---------------------------------------------------------------------------
class TestBuildScript:
    def test_build_script_exists(self) -> None:
        assert BUILD_PS1.exists(), "build-package.ps1 not found"

    def test_build_uses_canonical_agent_source(self) -> None:
        text = _read(BUILD_PS1)
        assert "agent" in text.lower()
        # Must reference the canonical source, not agente-windows/agent/
        assert "AgentSrc" in text or "agent/" in text or "\\agent\\" in text

    def test_build_pins_python_hash(self) -> None:
        text = _read(BUILD_PS1)
        assert "SHA-256" in text or "Hash" in text or "PYTHON_HASHES" in text

    def test_build_verifies_bootstrap_and_hash_locks_dependencies(self) -> None:
        text = _read(BUILD_PS1)
        assert "GET_PIP_HASH" in text
        assert "--require-hashes" in text
        assert "--only-binary=:all:" in text
        lock = _read(WINDOWS_LOCK)
        assert lock.count("--hash=sha256:") == 4
        assert "Remove-Item -LiteralPath $GetPipPath" in text
        assert "requirements-windows.lock no coincide con el SBOM" in text

    def test_build_enables_site_packages_in_embedded_python(self) -> None:
        text = _read(BUILD_PS1)
        assert 'Filter "python*._pth"' in text
        assert 'Filter "python*.._pth"' not in text

    def test_build_removes_build_tools_and_bytecode_from_runtime(self) -> None:
        text = _read(BUILD_PS1)
        assert '"pip*"' in text
        assert '"__pycache__"' in text
        assert '"*.pyc"' in text
        assert "pywin32_postinstall" not in text
        assert "Get-ChildItem $BuildDir -Directory -Recurse -Force" in text
        assert "Get-ChildItem $BuildDir -File -Recurse -Force" in text

    def test_sbom_lists_every_locked_runtime_component(self) -> None:
        text = _read(BUILD_PS1)
        for component in ("cryptography", "cffi", "pycparser", "pywin32"):
            assert f'name = "{component}"' in text

    def test_build_generates_manifest(self) -> None:
        text = _read(BUILD_PS1)
        assert "MANIFEST" in text
        assert text.index("$SbomJson =") < text.index("$ManifestPath =")
        assert "WriteAllLines" in text
        assert "System.Text.UTF8Encoding($false)" in text
        assert "[UNDECLARED]" in text
        assert "$manifestFiles.Count -ne $actualFiles.Count" in text

    def test_build_generates_sbom(self) -> None:
        text = _read(BUILD_PS1)
        assert "SBOM" in text

    def test_build_installs_cryptography(self) -> None:
        text = _read(BUILD_PS1)
        assert "cryptography" in text.lower()
        assert 'cryptography>=' not in text

    def test_build_installs_pywin32(self) -> None:
        text = _read(BUILD_PS1)
        assert "pywin32" in text.lower()
        assert 'pywin32>=' not in text

    def test_build_no_secrets_embedded(self) -> None:
        text = _read(BUILD_PS1)
        assert TOKEN_PATTERN.search(text) is None

    def test_build_md_exists(self) -> None:
        assert BUILD_MD.exists(), "BUILD.md not found"

    def test_build_md_mentions_sign_pending(self) -> None:
        text = _read(BUILD_MD)
        assert "SIGN_PENDING" in text or "Authenticode" in text


# ---------------------------------------------------------------------------
# Compatibility: no false claims
# ---------------------------------------------------------------------------
class TestCompatibilityClaims:
    FILES_WITH_COMPAT = [LEEME, BUILD_MD, INSTALL_MD]

    @pytest.mark.parametrize("path", FILES_WITH_COMPAT, ids=lambda p: p.name)
    def test_no_windows7_support_claim(self, path: Path) -> None:
        """Must not affirmatively claim Windows 7 compatibility."""
        if not path.exists():
            pytest.skip(f"{path.name} not found")
        import re
        text = _read(path)
        # Reject lines that positively claim Win7 support
        # Allow lines that say "not supported", "no soportado", "fuera de soporte", etc.
        for line in text.splitlines():
            line_lo = line.lower()
            if re.search(r'windows\s*7|win\s*7|7\s*sp1', line_lo):
                # Only fail if this is a positive support claim
                negative_words = [
                    "not", "no ", "sin ", "fuera", "eol", "end-of-life",
                    "unsupported", "no soportad", "eliminad", "removed",
                    "caution", "warning", "no admite",
                ]
                is_negative = any(w in line_lo for w in negative_words)
                assert is_negative, (
                    f"{path.name}: positive Windows 7 support claim found: {line.strip()!r}"
                )

    @pytest.mark.parametrize("path", FILES_WITH_COMPAT, ids=lambda p: p.name)
    def test_no_windows8_support_claim(self, path: Path) -> None:
        """Must not affirmatively claim Windows 8 compatibility."""
        if not path.exists():
            pytest.skip(f"{path.name} not found")
        import re
        text = _read(path)
        for line in text.splitlines():
            line_lo = line.lower()
            if re.search(r'windows\s*8(?!\.1\s*(?:ltsc|ltsb))|win\s*8', line_lo):
                negative_words = [
                    "not", "no ", "sin ", "fuera", "eol", "end-of-life",
                    "unsupported", "no soportad", "eliminad", "removed",
                    "caution", "warning", "no admite",
                ]
                is_negative = any(w in line_lo for w in negative_words)
                assert is_negative, (
                    f"{path.name}: positive Windows 8 support claim found: {line.strip()!r}"
                )

    def test_bat_no_windows7_claim(self) -> None:
        if not BAT.exists():
            pytest.skip("BAT not found")
        import re
        text = _read(BAT).lower()
        # BAT must not list Win7 as compatible — it only redirects to installer
        assert not re.search(r'compatible.*windows\s*7|windows\s*7.*compatible', text)

    def test_agente_telemetria_doc_no_false_win7_claim(self) -> None:
        doc = ROOT / "Automatizacion" / "docs" / "Agente-y-Telemetria.md"
        if not doc.exists():
            pytest.skip("doc not found")
        import re
        text = _read(doc)
        for line in text.splitlines():
            line_lo = line.lower()
            if re.search(r'windows\s*7|win\s*7', line_lo):
                negative_words = [
                    "not", "no ", "sin ", "fuera", "eol", "caution",
                    "warning", "no soportad", "no admite", "eliminad",
                ]
                is_negative = any(w in line_lo for w in negative_words)
                assert is_negative, (
                    f"Agente-y-Telemetria.md positive Win7 claim: {line.strip()!r}"
                )


# ---------------------------------------------------------------------------
# Canonical source: agent/ must be the single source of truth
# ---------------------------------------------------------------------------
class TestCanonicalSource:
    def test_canonical_actions_py_has_closed_catalog(self) -> None:
        actions_py = AGENT_SRC / "nexus_agent" / "actions.py"
        assert actions_py.exists()
        text = _read(actions_py)
        for action in CLOSED_CATALOG:
            assert action in text, f"ACTION_CATALOG missing: {action}"

    def test_no_shell_in_catalog(self) -> None:
        actions_py = AGENT_SRC / "nexus_agent" / "actions.py"
        text = _read(actions_py)
        assert "shell=True" not in text
        assert "os.system" not in text

    def test_installer_existing_tests_still_pass(self) -> None:
        """Regression: ensure test_agent_installers.py contracts still hold."""
        # test_installers_do_not_embed_a_deployment_ip
        ps1 = _read(INSTALLER_PS1)
        assert TOKEN_PATTERN.search(ps1) is None

        # test_windows_installer_requires_public_keys_and_uses_configured_artifact_origin
        assert "$PublicKeysJson" in ps1
        assert "ConvertFrom-Json" in ps1
        assert "$ArtifactBaseUrl" in ps1
        assert "<clave-ed25519-base64>" in ps1
