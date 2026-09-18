# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec para nexus-agent-setup.exe
# Produce un unico .exe autocontenido con el agente y todas sus dependencias.
#
# Ejecutar desde la raiz del repositorio:
#   .venv\Scripts\pyinstaller agente-windows\installer\nexus-agent-setup.spec

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

ROOT       = Path(SPECPATH).parent.parent          # raiz del repositorio
AGENT      = str(ROOT / "agent")                   # codigo canonico
SERVICE    = str(ROOT / "agente-windows" / "service")
VERSIONFILE = str(Path(SPECPATH) / "version_info.txt")

# PyInstaller executes the spec with its own import path.  Add the repository
# root before collecting the namespace so the bundled executable contains the
# canonical ``agent`` package (not runtime config files from that directory).
sys.path.insert(0, str(ROOT))

block_cipher = None

a = Analysis(
    [str(ROOT / "agente-windows" / "installer" / "nexus_agent_setup.py")],
    pathex=[str(ROOT), SERVICE],
    binaries=[],
    datas=[],
    hiddenimports=[
        # Codigo canonico; collect_submodules includes Python modules only and
        # cannot accidentally bundle ignored runtime configuration or secrets.
        *collect_submodules("agent"),
        "nexus_agent_service",
        # cryptography
        "cryptography",
        "cryptography.hazmat.primitives.asymmetric.ed25519",
        "cryptography.hazmat.backends",
        "cryptography.hazmat.backends.openssl",
        "cffi",
        "_cffi_backend",
        # pywin32 (para el modo servicio)
        "win32service",
        "win32serviceutil",
        "win32event",
        "servicemanager",
        "pywintypes",
        # stdlib que PyInstaller a veces omite
        "sqlite3",
        "json",
        "getpass",
        "ctypes",
        "ctypes.wintypes",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Excluir lo que no se necesita para reducir tamano
        "tkinter",
        "unittest",
        "test",
        "xmlrpc",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="nexus-agent-setup",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                # UPX puede activar antivirus — desactivado
    console=True,             # Consola visible para ver mensajes de instalacion
    icon=None,                # Agregar icono .ico si se tiene
    version=VERSIONFILE,      # Metadatos de version PE (Company, Product, etc.)
    uac_admin=True,           # Solicitar UAC administrador al ejecutar
    onefile=True,
)
