"""NEXUS IT Agent — Windows Service implementation using pywin32.

Registered as 'NexusITAgent' in the Windows Service Control Manager.
Runs as LocalSystem (minimum required for DPAPI machine-scope decryption
and SQLite state in ProgramData). The service does NOT accept arbitrary
commands; it only runs the closed-catalog agent loop.

Security constraints maintained:
- No shell, no PowerShell, no arbitrary command execution.
- Closed catalog only: restart_service, flush_dns,
  collect_extended_diagnostics, reboot_system.
- Ed25519 verification, nonce, TTL, anti-replay enforced by agent/actions.py.
- Token loaded from DPAPI-protected blob at startup, not from config JSON.
- Logs written to a file with SYSTEM+Administrators ACL; no secrets logged.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import sys
import time
from pathlib import Path

import servicemanager
import win32event
import win32service
import win32serviceutil

# ---------------------------------------------------------------------------
# Paths — all relative to INSTALL_DIR injected by the service installer
# ---------------------------------------------------------------------------
INSTALL_DIR = Path(
    os.environ.get("NEXUS_AGENT_INSTALL_DIR",
                   r"C:\ProgramData\NexusIT\Agent")
)
CONFIG_PATH      = INSTALL_DIR / "agent_config.json"
LOG_PATH         = INSTALL_DIR / "logs" / "agent.log"
DB_PATH          = INSTALL_DIR / "agent.db"
ACTIONS_DB_PATH  = INSTALL_DIR / "actions.sqlite3"
TOKEN_BLOB_PATH  = INSTALL_DIR / ".token.dpapi"

SERVICE_NAME         = "NexusITAgent"
SERVICE_DISPLAY_NAME = "NEXUS IT Agent"
SERVICE_DESCRIPTION  = (
    "Telemetry, inventory, and authorized remote-action agent for NEXUS IT. "
    "Closed action catalog only; no shell or arbitrary command execution."
)

ALLOWED_CONFIG_FIELDS = frozenset(
    {"server_url", "device_id", "hostname", "public_keys", "inventory_interval"}
)


# ---------------------------------------------------------------------------
# DPAPI helpers (machine scope — survives service account changes)
# ---------------------------------------------------------------------------
def _dpapi_protect(plaintext: bytes) -> bytes:
    """Encrypt with DPAPI machine scope."""
    import ctypes.wintypes
    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_byte))]

    src = (ctypes.c_byte * len(plaintext))(*plaintext)
    blob_in  = _BLOB(cbData=len(plaintext), pbData=src)
    blob_out = _BLOB()
    CRYPTPROTECT_LOCAL_MACHINE = 0x4
    ok = ctypes.windll.crypt32.CryptProtectData(  # type: ignore[attr-defined]
        ctypes.byref(blob_in), None, None, None, None,
        CRYPTPROTECT_LOCAL_MACHINE,
        ctypes.byref(blob_out),
    )
    if not ok:
        raise OSError("DPAPI CryptProtectData failed")
    result = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    ctypes.windll.kernel32.LocalFree(blob_out.pbData)  # type: ignore[attr-defined]
    return result


def _dpapi_unprotect(ciphertext: bytes) -> bytes:
    """Decrypt with DPAPI machine scope."""

    import ctypes.wintypes

    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_byte))]

    src = (ctypes.c_byte * len(ciphertext))(*ciphertext)
    blob_in  = _BLOB(cbData=len(ciphertext), pbData=src)
    blob_out = _BLOB()
    CRYPTPROTECT_LOCAL_MACHINE = 0x4
    ok = ctypes.windll.crypt32.CryptUnprotectData(  # type: ignore[attr-defined]
        ctypes.byref(blob_in), None, None, None, None,
        CRYPTPROTECT_LOCAL_MACHINE,
        ctypes.byref(blob_out),
    )
    if not ok:
        raise OSError("DPAPI CryptUnprotectData failed — invalid blob or wrong machine")
    result = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    ctypes.windll.kernel32.LocalFree(blob_out.pbData)  # type: ignore[attr-defined]
    return result


def store_token_dpapi(token: str) -> None:
    """Encrypt and persist the agent token using DPAPI machine scope."""
    TOKEN_BLOB_PATH.parent.mkdir(parents=True, exist_ok=True)
    blob = _dpapi_protect(token.encode("utf-8"))
    TOKEN_BLOB_PATH.write_bytes(blob)
    _harden_path(TOKEN_BLOB_PATH)


def load_token_dpapi() -> str:
    """Load and decrypt the agent token from the DPAPI blob."""
    if not TOKEN_BLOB_PATH.exists():
        raise FileNotFoundError(
            f"Token blob not found: {TOKEN_BLOB_PATH}. "
            "Re-install the agent and provide the token."
        )
    blob = TOKEN_BLOB_PATH.read_bytes()
    return _dpapi_unprotect(blob).decode("utf-8")


def store_token_from_stdin() -> None:
    """Read one token from stdin so it never appears in the process command line."""
    token = sys.stdin.read().rstrip("\r\n")
    if len(token) < 10 or len(token) > 512 or any(char.isspace() for char in token):
        raise ValueError("invalid agent token")
    store_token_dpapi(token)


# ---------------------------------------------------------------------------
# ACL helper
# ---------------------------------------------------------------------------
def _harden_path(path: Path) -> None:
    """Apply SYSTEM+Administrators-only ACL via icacls using well-known SIDs.

    Raises OSError if any icacls command fails.
    """
    import subprocess
    target = str(path)
    # Use SIDs to avoid locale-dependent name resolution
    steps = [
        (["icacls", target, "/inheritance:r"], "remove inheritance"),
        (["icacls", target, "/grant:r", "*S-1-5-18:(F)"], "grant SYSTEM (SID)"),
        (["icacls", target, "/grant:r", "*S-1-5-32-544:(F)"], "grant Administrators (SID)"),
    ]
    for cmd, desc in steps:
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise OSError(
                f"icacls failed ({desc}): exit {r.returncode}\n"
                f"  stdout: {r.stdout.strip()}\n"
                f"  stderr: {r.stderr.strip()}"
            )


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------
def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    raw = json.loads(CONFIG_PATH.read_text("utf-8"))
    if not isinstance(raw, dict):
        return {}
    unknown = set(raw) - ALLOWED_CONFIG_FIELDS
    if unknown:
        raise ValueError(f"agent_config.json has unsupported fields: {unknown}")
    return raw


# ---------------------------------------------------------------------------
# Logging — file + Windows Event Log; never logs secrets
# ---------------------------------------------------------------------------
def _setup_logging() -> logging.Logger:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(SERVICE_NAME)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fh = logging.FileHandler(str(LOG_PATH), encoding="utf-8")
        fh.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        ))
        logger.addHandler(fh)
    return logger


# ---------------------------------------------------------------------------
# Windows Service class
# ---------------------------------------------------------------------------
class NexusAgentService(win32serviceutil.ServiceFramework):
    _svc_name_         = SERVICE_NAME
    _svc_display_name_ = SERVICE_DISPLAY_NAME
    _svc_description_  = SERVICE_DESCRIPTION

    def __init__(self, args):  # type: ignore[override]
        win32serviceutil.ServiceFramework.__init__(self, args)
        self._stop_event = win32event.CreateEvent(None, 0, 0, None)
        self._logger = _setup_logging()

    def SvcStop(self) -> None:
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self._stop_event)
        self._logger.info("Stop signal received.")

    def SvcDoRun(self) -> None:
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        self._logger.info("NexusITAgent service starting.")
        try:
            self._run()
        except Exception as exc:
            self._logger.error("Fatal error in agent service: %s", exc)
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_ERROR_TYPE,
                servicemanager.PYS_SERVICE_STOPPED,
                (self._svc_name_, str(exc)),
            )
            raise
        finally:
            self._logger.info("NexusITAgent service stopped.")

    def _run(self) -> None:
        # Resolve install dir
        install_dir = INSTALL_DIR
        sys.path.insert(0, str(install_dir))

        # Load config (no secrets)
        config = _load_config()

        # Load token from DPAPI — never from config JSON
        try:
            token = load_token_dpapi()
        except Exception as exc:
            self._logger.error("Cannot load agent token: %s. Service stopping.", exc)
            raise RuntimeError("agent token unavailable") from exc

        # Resolve server URL
        server_url = (
            os.environ.get("NEXUS_AGENT_SERVER_URL", "")
            or str(config.get("server_url", ""))
        ).strip().rstrip("/")

        if not server_url:
            self._logger.error("server_url not configured. Service stopping.")
            raise RuntimeError("server_url not configured")

        device_id = str(config.get("device_id", "")).strip()
        if not device_id:
            self._logger.error("device_id not configured. Service stopping.")
            raise RuntimeError("device_id not configured")

        # Import agent (available in sys.path after build)
        try:
            from agent.run_agent import (  # type: ignore[import]
                NexusAgent,
                LocalQueue,
                SQLiteActionStore,
                make_action_handlers,
                parse_public_keys,
                validate_server_url,
            )
            from agent.nexus_agent.protection import WindowsDpapiProtector  # type: ignore[import]
        except ImportError as exc:
            self._logger.error("Agent code not found in install directory: %s", exc)
            raise RuntimeError("bundled agent code unavailable") from exc

        try:
            validated_url = validate_server_url(server_url, allow_insecure_http=False)
        except ValueError as exc:
            self._logger.error("Invalid server_url: %s", exc)
            raise RuntimeError("invalid server_url") from exc

        protector = WindowsDpapiProtector()
        queue = LocalQueue(DB_PATH, protector=protector)
        action_store = SQLiteActionStore(ACTIONS_DB_PATH)
        action_store.reconcile_after_restart(now_epoch=int(time.time()))
        public_keys = parse_public_keys(config.get("public_keys"), environment=os.environ)

        hostname = str(config.get("hostname", "")).strip() or None
        inventory_interval = max(30, int(config.get("inventory_interval", 300)))

        agent = NexusAgent(
            validated_url,
            device_id,
            token,
            queue,
            action_store=action_store,
            public_keys=public_keys,
            hostname=hostname,
            action_handlers=make_action_handlers(),
        )

        self._logger.info(
            "Agent running. device=%s server=%s", device_id, validated_url
        )
        last_inventory = 0.0
        interval = 30

        while win32event.WaitForSingleObject(self._stop_event, 0) != win32event.WAIT_OBJECT_0:
            try:
                from agent.nexus_agent.storage import QueueCapacityExceeded  # type: ignore[import]
                try:
                    agent.collect_and_enqueue()
                except QueueCapacityExceeded:
                    self._logger.warning("Telemetry queue full; protected records preserved.")
                outcome = agent.dispatcher.dispatch_once().outcome
                self._logger.debug("Telemetry dispatch: %s", outcome)

                now = time.time()
                if now - last_inventory >= inventory_interval:
                    inv_res = agent.collect_and_send_inventory()
                    inv_ok = 200 <= inv_res.status_code < 300
                    self._logger.info("Inventory dispatch: %s", "OK" if inv_ok else f"FAILED({inv_res.status_code})")
                    last_inventory = now

                executed = agent.poll_and_execute_actions()
                if executed > 0:
                    self._logger.info("Remote actions executed: %d", executed)

            except Exception as exc:
                self._logger.error("Agent loop error: %s", exc)

            # Sleep in 1-second chunks to respond to stop signal promptly
            for _ in range(interval):
                if win32event.WaitForSingleObject(self._stop_event, 1000) == win32event.WAIT_OBJECT_0:
                    return

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if sys.argv[1:] == ["--store-token-stdin"]:
        store_token_from_stdin()
    elif len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(NexusAgentService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(NexusAgentService)
