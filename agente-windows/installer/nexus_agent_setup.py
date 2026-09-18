"""NEXUS IT Agent — Instalador de un solo archivo (.exe).

Este script es el punto de entrada del ejecutable producido por PyInstaller.
Al ejecutarse:
  - Sin argumentos: modo instalador interactivo (pide token en pantalla).
  - Con --server-url, --device-id, --public-keys: instalación silenciosa (pide token).
  - Con --service: modo servicio (llamado internamente por el SCM).
  - Con --uninstall: desinstala el servicio.

El token NUNCA se pasa como argumento de línea de comandos ni se escribe en disco
en texto plano. Se protege con DPAPI antes de almacenarse.
"""

from __future__ import annotations

__version__ = "1.0.0"

import argparse
import base64
import binascii
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
from getpass import getpass
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

INSTALL_DIR    = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "NexusIT" / "Agent"
SERVICE_NAME   = "NexusITAgent"
SERVICE_DISPLAY = "NEXUS IT Agent"
TOKEN_BLOB     = INSTALL_DIR / ".token.dpapi"
CONFIG_FILE    = INSTALL_DIR / "agent_config.json"
LOG_DIR        = INSTALL_DIR / "logs"

ALLOWED_CONFIG_FIELDS = frozenset(
    {"server_url", "device_id", "hostname", "public_keys", "inventory_interval"}
)


# ---------------------------------------------------------------------------
# DPAPI — cifrado de máquina para el token
# ---------------------------------------------------------------------------
def _dpapi_protect(plaintext: bytes) -> bytes:
    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_ulong),
                    ("pbData", ctypes.POINTER(ctypes.c_byte))]
    src = (ctypes.c_byte * len(plaintext))(*plaintext)
    b_in  = _BLOB(cbData=len(plaintext), pbData=src)
    b_out = _BLOB()
    ok = ctypes.windll.crypt32.CryptProtectData(  # type: ignore[attr-defined]
        ctypes.byref(b_in), None, None, None, None, 0x4, ctypes.byref(b_out))
    if not ok:
        raise OSError("DPAPI: CryptProtectData fallo")
    result = ctypes.string_at(b_out.pbData, b_out.cbData)
    ctypes.windll.kernel32.LocalFree(b_out.pbData)  # type: ignore[attr-defined]
    return result


def _dpapi_unprotect(ciphertext: bytes) -> bytes:
    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_ulong),
                    ("pbData", ctypes.POINTER(ctypes.c_byte))]
    src = (ctypes.c_byte * len(ciphertext))(*ciphertext)
    b_in  = _BLOB(cbData=len(ciphertext), pbData=src)
    b_out = _BLOB()
    ok = ctypes.windll.crypt32.CryptUnprotectData(  # type: ignore[attr-defined]
        ctypes.byref(b_in), None, None, None, None, 0x4, ctypes.byref(b_out))
    if not ok:
        raise OSError("DPAPI: CryptUnprotectData fallo — blob invalido o maquina incorrecta")
    result = ctypes.string_at(b_out.pbData, b_out.cbData)
    ctypes.windll.kernel32.LocalFree(b_out.pbData)  # type: ignore[attr-defined]
    return result


def store_token(token: str) -> None:
    TOKEN_BLOB.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_BLOB.write_bytes(_dpapi_protect(token.encode("utf-8")))
    _harden(TOKEN_BLOB)


def load_token() -> str:
    if not TOKEN_BLOB.exists():
        raise FileNotFoundError("Token no encontrado. Re-instale el agente.")
    return _dpapi_unprotect(TOKEN_BLOB.read_bytes()).decode("utf-8")


# ---------------------------------------------------------------------------
# ACL — solo SYSTEM y Administrators
# ---------------------------------------------------------------------------
def _harden(path: Path) -> None:
    """Apply restrictive ACL: only SYSTEM and Administrators get full control.

    Raises OSError if any icacls command fails.
    """
    target = str(path)
    system_grant = "*S-1-5-18:(OI)(CI)(F)" if path.is_dir() else "*S-1-5-18:(F)"
    admins_grant = "*S-1-5-32-544:(OI)(CI)(F)" if path.is_dir() else "*S-1-5-32-544:(F)"
    recursive = ["/T", "/Q"] if path.is_dir() else []
    steps = [
        (["icacls", target, "/inheritance:r", *recursive], "remove inheritance"),
        (["icacls", target, "/grant:r", system_grant, *recursive], "grant SYSTEM (SID)"),
        (["icacls", target, "/grant:r", admins_grant, *recursive], "grant Administrators (SID)"),
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
# Validar URL del servidor
# ---------------------------------------------------------------------------
def _validate_url(url: str, allow_http: bool = False) -> str:
    url = url.strip().rstrip("/")
    parsed = urlsplit(url)
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise ValueError("La URL debe contener solo esquema, host y puerto opcional")
    if parsed.scheme == "https":
        return url
    if parsed.scheme == "http" and allow_http:
        if parsed.hostname.lower() in ("localhost", "127.0.0.1", "::1"):
            return url
        raise ValueError("HTTP solo se permite en loopback. Use https://")
    raise ValueError(f"URL invalida: {url!r}. Debe comenzar con https://")


def _validate_device_id(value: str) -> str:
    try:
        identifier = UUID(value.strip())
    except ValueError:
        raise ValueError("device_id debe ser un UUIDv4 valido") from None
    if identifier.version != 4:
        raise ValueError("device_id debe ser un UUIDv4")
    return str(identifier)


def _validate_public_keys(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        raise ValueError("public_keys debe ser un objeto JSON no vacio")
    validated: dict[str, str] = {}
    for raw_version, raw_key in value.items():
        try:
            version = int(raw_version)
        except (TypeError, ValueError):
            raise ValueError("cada version de clave debe ser un entero positivo") from None
        if version <= 0 or not isinstance(raw_key, str):
            raise ValueError("cada clave Ed25519 debe tener version positiva y valor base64")
        try:
            decoded = base64.b64decode(raw_key.strip(), validate=True)
        except (binascii.Error, ValueError):
            raise ValueError(f"clave Ed25519 version {version} no es base64 valido") from None
        if len(decoded) != 32:
            raise ValueError(f"clave Ed25519 version {version} debe contener 32 bytes")
        validated[str(version)] = raw_key.strip()
    return validated


# ---------------------------------------------------------------------------
# Instalar agente como Windows Service
# ---------------------------------------------------------------------------
def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except Exception:
        return False


def _exe_path() -> Path:
    """Ruta del .exe actual (funciona con PyInstaller y con Python directo)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    return Path(sys.argv[0]).resolve()


def _install_exe(install_dir: Path) -> Path:
    """Copy the running exe atomically into the install directory.

    Returns the path of the installed copy. If already running from
    install_dir, returns the current path without copying.
    """
    src = _exe_path()
    dst = install_dir / src.name
    if src.resolve() == dst.resolve():
        return dst
    install_dir.mkdir(parents=True, exist_ok=True)
    # Atomic: write to temp, then rename
    tmp = dst.with_suffix(".tmp")
    shutil.copy2(str(src), str(tmp))
    tmp.replace(dst)  # atomic on NTFS
    return dst


def _service_exists() -> bool:
    return subprocess.run(
        ["sc", "query", SERVICE_NAME], capture_output=True, text=True
    ).returncode == 0


def _run_sc(*arguments: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["sc", *arguments], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"sc.exe fallo (exit {result.returncode}): {' '.join(arguments)}; "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result


def _stop_existing_service() -> None:
    query = subprocess.run(
        ["sc", "query", SERVICE_NAME], capture_output=True, text=True
    )
    if "STOPPED" not in query.stdout:
        _run_sc("stop", SERVICE_NAME)
    deadline = time.time() + 30
    while time.time() < deadline:
        query = subprocess.run(
            ["sc", "query", SERVICE_NAME], capture_output=True, text=True
        )
        if "STOPPED" in query.stdout:
            return
        time.sleep(0.5)
    raise RuntimeError("No se pudo detener el servicio existente antes de actualizar")


def _wait_service_removed() -> None:
    deadline = time.time() + 30
    while time.time() < deadline:
        if not _service_exists():
            return
        time.sleep(0.5)
    raise RuntimeError("El servicio quedo marcado para eliminacion y no desaparecio a tiempo")


def _purge_install_directory() -> bool:
    """Remove sensitive data now; defer the running installed exe until reboot.

    Returns True when the complete directory was deleted immediately, False when
    Windows scheduled the current executable and directory for deletion at reboot.
    """
    if not INSTALL_DIR.exists():
        return True
    current_exe = _exe_path().resolve()
    try:
        running_from_install = current_exe.is_relative_to(INSTALL_DIR.resolve())
    except ValueError:
        running_from_install = False
    if not running_from_install:
        shutil.rmtree(INSTALL_DIR)
        if INSTALL_DIR.exists():
            raise RuntimeError(f"No se pudo eliminar {INSTALL_DIR}")
        return True

    for child in INSTALL_DIR.iterdir():
        if child.resolve() == current_exe:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()

    move_file_ex = ctypes.windll.kernel32.MoveFileExW  # type: ignore[attr-defined]
    move_file_ex.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_ulong]
    move_file_ex.restype = ctypes.c_int
    movefile_delay_until_reboot = 0x4
    for pending in (current_exe, INSTALL_DIR.resolve()):
        if not move_file_ex(str(pending), None, movefile_delay_until_reboot):
            raise OSError(ctypes.get_last_error(), f"No se pudo programar borrado: {pending}")
    return False


def _cleanup_partial_install() -> None:
    """Best-effort rollback for a failed fresh installation."""
    if _service_exists():
        try:
            _stop_existing_service()
        finally:
            _run_sc("delete", SERVICE_NAME)
            _wait_service_removed()
    if INSTALL_DIR.exists():
        shutil.rmtree(INSTALL_DIR)


def cmd_install(args: argparse.Namespace) -> None:
    if not _is_admin():
        print("[!] Se requieren permisos de Administrador.", file=sys.stderr)
        sys.exit(1)

    if _service_exists():
        print(
            "[X] NexusITAgent ya esta instalado. Use el paquete ZIP y "
            "nexus-agent-ctl.ps1 update para actualizarlo.",
            file=sys.stderr,
        )
        sys.exit(1)
    if INSTALL_DIR.exists():
        print(
            f"[X] Ya existe {INSTALL_DIR}. Revise o elimine manualmente los residuos.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        _cmd_install_fresh(args)
    except Exception as exc:
        print(f"[X] Instalacion fallida: {exc}", file=sys.stderr)
        try:
            _cleanup_partial_install()
        except Exception as cleanup_exc:
            print(f"[!] Limpieza incompleta: {cleanup_exc}", file=sys.stderr)
        raise


def _cmd_install_fresh(args: argparse.Namespace) -> None:

    server_url = args.server_url or input("URL del servidor (https://...): ").strip()
    device_id  = args.device_id  or input("ID de dispositivo (UUID): ").strip()
    public_keys_raw = args.public_keys or input('Claves publicas JSON ({"1":"<b64>"}): ').strip()

    try:
        server_url = _validate_url(server_url, allow_http=args.allow_insecure_http)
        device_id = _validate_device_id(device_id)
        public_keys = _validate_public_keys(json.loads(public_keys_raw))
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"[X] Error de validacion: {exc}", file=sys.stderr)
        sys.exit(1)

    token = getpass("Token del agente (no se mostrara en pantalla): ").strip()
    if len(token) < 10:
        print("[X] Token invalido o vacio.", file=sys.stderr)
        sys.exit(1)

    print("\n[1/6] Creando directorio de instalacion...")
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(exist_ok=True)
    _harden(INSTALL_DIR)
    _harden(LOG_DIR)

    print("[2/6] Guardando configuracion no-secreta...")
    config = {
        "server_url":        server_url,
        "device_id":         device_id,
        "hostname":          os.environ.get("COMPUTERNAME", ""),
        "inventory_interval": 300,
        "public_keys":       public_keys,
    }
    unknown = set(config) - ALLOWED_CONFIG_FIELDS
    assert not unknown, f"Campos invalidos: {unknown}"
    CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")
    _harden(CONFIG_FILE)
    print(f"    Config: {CONFIG_FILE}")

    print("[3/6] Protegiendo token con DPAPI...")
    store_token(token)
    token = ""  # limpiar de memoria
    print("    Token cifrado con DPAPI (cifrado de maquina).")

    print("[4/6] ACL NTFS segura aplicada.")

    print("[5/6] Copiando ejecutable a directorio de instalacion...")
    installed_exe = _install_exe(INSTALL_DIR)
    _harden(installed_exe)
    print(f"    Ejecutable: {installed_exe}")

    print("[6/6] Registrando Windows Service...")
    exe = str(installed_exe)
    # Crear el servicio; las actualizaciones se realizan con el paquete ZIP.
    # El exe detecta que fue llamado por el SCM (sin TTY/consola)
    # y entra en modo servicio.
    bin_path = f'"{exe}" --service'
    _run_sc(
        "create", SERVICE_NAME,
        "binPath=", bin_path,
        "DisplayName=", SERVICE_DISPLAY,
        "start=", "delayed-auto",
    )
    _run_sc(
        "description", SERVICE_NAME,
        "NEXUS IT monitoring agent. Closed action catalog only.",
    )
    _run_sc(
        "failure", SERVICE_NAME,
        "reset=", "3600",
        "actions=", "restart/60000/restart/60000/restart/60000",
    )

    _run_sc("start", SERVICE_NAME)

    # Esperar estado RUNNING
    deadline = time.time() + 30
    while time.time() < deadline:
        r = subprocess.run(["sc", "query", SERVICE_NAME],
                           capture_output=True, text=True)
        if "RUNNING" in r.stdout:
            print("\n[OK] Servicio NexusITAgent RUNNING.")
            print(f"     Ejecutable: {installed_exe}")
            print(f"     Datos en : {INSTALL_DIR}")
            print("     Para desinstalar: nexus-agent-setup.exe --uninstall")
            return
        time.sleep(1)

    raise RuntimeError("El servicio no arranco a tiempo. Revise el Event Log.")


# ---------------------------------------------------------------------------
# Modo servicio (llamado por el SCM)
# ---------------------------------------------------------------------------
def cmd_service() -> None:
    """Punto de entrada cuando el SCM arranca el servicio.

    Called as: nexus-agent-setup.exe --service
    The SCM passes no additional args, so sys.argv is ['path', '--service'].
    We must strip our own flag and present a clean argv to pywin32's
    ServiceFramework, which expects either no args (for SCM dispatch) or
    service-control verbs like 'install', 'start', 'remove'.
    """
    # Strip our own --service flag so pywin32 sees a clean argv
    sys.argv = [sys.argv[0]]

    try:
        import servicemanager  # type: ignore[import]
        import win32serviceutil  # type: ignore[import]
        # Import the service class bundled alongside this exe
        from nexus_agent_service import NexusAgentService  # type: ignore[import]

        # No args left → SCM is starting us: connect to the dispatcher
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(NexusAgentService)
        servicemanager.StartServiceCtrlDispatcher()
    except ImportError as exc:
        raise RuntimeError(
            "Dependencias pywin32 del servicio no disponibles en el ejecutable."
        ) from exc


# ---------------------------------------------------------------------------
# Desinstalar
# ---------------------------------------------------------------------------
def cmd_uninstall(purge: bool = False) -> None:
    if not _is_admin():
        print("[!] Se requieren permisos de Administrador.", file=sys.stderr)
        sys.exit(1)
    if _service_exists():
        print("Deteniendo servicio...")
        _stop_existing_service()
        _run_sc("delete", SERVICE_NAME)
        _wait_service_removed()
        print("[OK] Servicio eliminado.")
    else:
        print("[i] Servicio no instalado.")
    if purge and INSTALL_DIR.exists():
        deleted_now = _purge_install_directory()
        if deleted_now:
            print(f"[OK] Datos eliminados: {INSTALL_DIR}")
        else:
            print("[OK] Datos sensibles eliminados. Ejecutable y directorio se borraran al reiniciar.")
    else:
        print(f"[i] Datos conservados en: {INSTALL_DIR}")
    print("Desinstalacion completada.")


# ---------------------------------------------------------------------------
# Estado
# ---------------------------------------------------------------------------
def cmd_status() -> None:
    r = subprocess.run(["sc", "query", SERVICE_NAME],
                       capture_output=True, text=True)
    if "RUNNING" in r.stdout:
        print(f"[OK] {SERVICE_NAME}: RUNNING")
    elif "STOPPED" in r.stdout:
        print(f"[!] {SERVICE_NAME}: STOPPED")
    else:
        print(f"[X] {SERVICE_NAME}: NO INSTALADO")
    if CONFIG_FILE.exists():
        cfg = json.loads(CONFIG_FILE.read_text("utf-8"))
        print(f"    Servidor   : {cfg.get('server_url', '?')}")
        print(f"    Dispositivo: {cfg.get('device_id', '?')}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="NEXUS IT Agent — Instalador",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  nexus-agent-setup.exe                          # instalador interactivo
  nexus-agent-setup.exe --status                 # ver estado del servicio
  nexus-agent-setup.exe --uninstall              # desinstalar
  nexus-agent-setup.exe --uninstall --purge      # desinstalar + borrar datos
        """,
    )
    parser.add_argument("--server-url",   default="", help="URL HTTPS del servidor")
    parser.add_argument("--device-id",    default="", help="UUID del dispositivo")
    parser.add_argument("--public-keys",  default="", help='JSON de claves Ed25519, ej: \'{"1":"<b64>"}\'')
    parser.add_argument("--service",      action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--uninstall",    action="store_true", help="Desinstalar el servicio")
    parser.add_argument("--purge",        action="store_true", help="Con --uninstall: eliminar datos")
    parser.add_argument("--status",       action="store_true", help="Ver estado del servicio")
    parser.add_argument("--allow-insecure-http", action="store_true",
                        help="Permitir HTTP en loopback (solo desarrollo)")

    args = parser.parse_args()

    if args.service:
        cmd_service()
    elif args.uninstall:
        cmd_uninstall(purge=args.purge)
    elif args.status:
        cmd_status()
    else:
        print("=" * 52)
        print("   NEXUS IT Agent — Instalador")
        print("=" * 52)
        cmd_install(args)


if __name__ == "__main__":
    main()
