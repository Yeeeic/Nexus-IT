# NEXUS IT Agent — Windows Package Build Instructions

## Requisitos de construcción

| Herramienta | Versión mínima | Propósito |
|---|---|---|
| PowerShell | 5.1+ | Script de build |
| Python | 3.13.3 embeddable | Runtime del paquete ZIP |
| pip | 26.2.1 | Instalación reproducible con hashes |
| git | cualquiera | Clonar fuente canónica |

## Runtime embebido (Python 3.13.x — x64)

El build descarga y verifica el runtime oficial de python.org.

```
Archivo : python-3.13.3-embed-amd64.zip
SHA-256 : 59ff76e16e6597de47474fb22be69e7191a89116910d728ab735079b078e52db
URL     : https://www.python.org/ftp/python/3.13.3/python-3.13.3-embed-amd64.zip
Licencia: PSF-2.0
```

> [!IMPORTANT]
> Nunca usar el runtime de `agente-windows/` anterior (Python 3.8.10 + OpenSSL 1.1.1k, EOL).
> Siempre descargar el runtime desde python.org con verificación de hash.

## Dependencias del agente

| Paquete | Versión fijada | Licencia |
|---|---|---|
| cryptography | 50.0.1 | Apache-2.0 / BSD |
| cffi | 2.1.1 | MIT-0 (transitiva de cryptography) |
| pycparser | 2.23 | BSD-3-Clause (transitiva de cffi) |
| pywin32 | 312 | PSF-2.0 |

**Justificación de dependencias:**
- `cryptography`: requerida por verificación Ed25519 (`actions.py`). Mantenida por PyCA, auditoría activa.
- `pywin32`: requerida para implementar Windows Service real vía `win32service`. Sin alternativa stdlib.
- `cffi`: transitiva de `cryptography`; no se añade directamente.

## Proceso de construcción

```powershell
# Desde la raíz del repositorio, con PowerShell como administrador:
.\agente-windows\build-package.ps1
```

El script:
1. Descarga Python 3.13 embeddable y verifica SHA-256.
2. Instala pip en el runtime embebido.
3. Verifica `get-pip.py` e instala el lock `requirements-windows.lock` con `--require-hashes`.
4. Copia `agent/` desde la fuente canónica.
5. Sincroniza `agente-windows/agent_config.example.json` con `agent/agent_config.example.json`.
6. Genera `MANIFEST.sha256` con hash de cada archivo.
7. Genera `SBOM.json` con versiones y licencias.
8. Empaqueta `nexus-it-agent-windows-x64-<version>.zip`.

## Verificación del artefacto

```powershell
# Verificar que el manifiesto coincide con el contenido real:
.\agente-windows\build-package.ps1 -Version 1.0.0 -Verify
```

## Ejecutable único

El instalador autocontenido se construye desde la raíz del repositorio:

```powershell
.\.venv\Scripts\pyinstaller.exe `
    agente-windows\installer\nexus-agent-setup.spec `
    --distpath agente-windows\dist `
    --workpath agente-windows\.build-work `
    --noconfirm
```

Antes de distribuirlo, comprobar que el archivo de advertencias de PyInstaller
no reporte módulos `agent.*` ausentes y que el archivo contenga `agent.run_agent`,
`agent.nexus_agent.*` y `nexus_agent_service`. La build del `.exe` no se considera
reproducible byte a byte hasta fijar también SO, Python, PyInstaller y bootloader.

## Firma Authenticode (SIGN_PENDING)

El ejecutable y los scripts distribuibles deben firmarse con un certificado Code Signing
antes de distribución en producción. Pasos cuando el certificado esté disponible:

```powershell
signtool sign /fd sha256 /tr http://timestamp.digicert.com /td sha256 `
    /n "NEXUS IT" agente-windows\dist\nexus-agent-setup.exe

signtool verify /pa /all /v agente-windows\dist\nexus-agent-setup.exe
```

Un ZIP no se firma con Authenticode. Se distribuye mediante HTTPS con SHA-256
inmutable y manifiesto interno verificado; idealmente desde una publicación firmada.

**Estado:** SIGN_PENDING — bloqueo externo. Sin certificado activo.

## Notas de seguridad

- El artefacto producido NO debe contener tokens, UUIDs de despliegue, IPs ni claves privadas.
- `test_windows_agent_package.py` verifica estos contratos estáticamente.
- El token del agente se inyecta en la instalación mediante DPAPI; nunca va en el ZIP.
