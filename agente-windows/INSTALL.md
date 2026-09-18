# NEXUS IT Agent — Guía de Instalación, Actualización y Desinstalación

## Requisitos del sistema

| Requisito | Valor |
|---|---|
| Arquitectura | x64 (AMD64) |
| Sistema operativo mínimo | Windows 10 LTSC 21H2, Windows 11 23H2, Windows Server 2016 |
| Privilegios de instalación | Administrador local |
| Acceso de red | HTTPS hacia el servidor NEXUS IT |
| Python preinstalado | No requerido (runtime embebido incluido) |

> [!WARNING]
> Windows 7, 8 y 8.1 no están soportados. El runtime Python 3.13 no soporta
> versiones anteriores a Windows 8.1 y Microsoft no ofrece parches de seguridad para ellos.

## Antes de instalar

1. **Enrole el dispositivo** en la consola autenticada de NEXUS IT.
2. Anote el **ID de Dispositivo** (UUID) y el **Token** que se muestran una sola vez.
3. Descargue el paquete ZIP desde la consola o desde el enlace proporcionado por su administrador.
4. Verifique el hash SHA-256 del ZIP contra el valor publicado en la consola.

## Instalación sencilla con un solo `.exe`

Para una instalación inicial manual, entregue únicamente
`nexus-agent-setup.exe`. Ejecútelo con doble clic, acepte el UAC y capture URL,
UUIDv4, claves públicas Ed25519 y token. El instalador cifra el token con DPAPI y
crea `NexusITAgent`. Rechaza servicios o directorios existentes para evitar mezclar
una instalación nueva con datos residuales; las actualizaciones usan el paquete ZIP.

```powershell
.\nexus-agent-setup.exe
.\nexus-agent-setup.exe --status
.\nexus-agent-setup.exe --uninstall
.\nexus-agent-setup.exe --uninstall --purge
```

El `.exe` no sustituye todavía un canal central de despliegue. Para actualización
con rollback local se usa el paquete ZIP descrito a continuación.

## Instalación operativa con paquete ZIP

```powershell
# PowerShell como Administrador
cd C:\ruta\al\paquete\extraido

.\nexus-agent-ctl.ps1 install `
    -ServerUrl "https://nexus.suempresa.com" `
    -DeviceId "<uuid-del-dispositivo>" `
    -PublicKeysJson '{"1":"<clave-ed25519-base64>"}'
# El script pedirá el token de forma segura (no se muestra en pantalla)
```

El instalador:
- Extrae el runtime y el código en `C:\ProgramData\NexusIT\Agent`.
- Aplica ACL NTFS (solo SYSTEM y Administrators).
- Protege el token con DPAPI (cifrado de máquina).
- Crea el Windows Service `NexusITAgent` con inicio automático retrasado.
- Configura reinicios automáticos tras fallos.
- Espera confirmación de estado `RUNNING` antes de reportar éxito.

## Actualización

```powershell
# Con el nuevo paquete extraído:
.\nexus-agent-ctl.ps1 update -PackagePath "C:\ruta\al\nuevo\paquete"
```

La actualización:
- Detiene el servicio.
- Crea un respaldo del directorio de instalación anterior.
- Instala la nueva versión.
- Reinicia el servicio.
- Si el servicio no arranca, ejecuta rollback automático.

## Rollback manual

```powershell
.\nexus-agent-ctl.ps1 rollback
```

## Parar / Iniciar manualmente

```powershell
.\nexus-agent-ctl.ps1 stop
.\nexus-agent-ctl.ps1 start
.\nexus-agent-ctl.ps1 status
```

O mediante el Administrador de servicios:
```
sc query NexusITAgent
sc stop  NexusITAgent
sc start NexusITAgent
```

## Desinstalación

```powershell
# Preserva datos (SQLite, logs):
.\nexus-agent-ctl.ps1 uninstall

# Elimina TODOS los datos (irreversible):
.\nexus-agent-ctl.ps1 uninstall -Purge
```

## Solución de problemas

| Síntoma | Causa probable | Solución |
|---|---|---|
| Servicio no arranca | Token inválido o revocado | Re-enrolar desde consola |
| Estado STOPPED tras reinicio | Error en config | Revisar Event Log → Application → NexusITAgent |
| SmartScreen bloquea | Sin firma Authenticode | Contactar al administrador (SIGN_PENDING) |
| Error 1053 (timeout inicio) | El proceso no conectó a tiempo con SCM | Revisar Event Log, integridad del paquete y módulos incluidos |
| Telemetría no llega | HTTP en lugar de HTTPS | Verificar ServerUrl comienza con `https://` |

### Ver logs

```powershell
# Event Log:
Get-EventLog -LogName Application -Source NexusITAgent -Newest 50

# Archivo de log:
Get-Content "C:\ProgramData\NexusIT\Agent\logs\agent.log" -Tail 100
```

## Ruta de instalación

```
C:\ProgramData\NexusIT\Agent\
├── runtime\          ← Python embeddable (solo lectura)
├── agent\            ← Código del agente (solo lectura)
├── service\          ← Scripts de servicio (solo lectura)
├── agent_config.json ← Config no-secreta (SYSTEM+Admins)
├── agent.db          ← Cola SQLite WAL (SYSTEM+Admins)
├── actions.sqlite3   ← Estado de acciones (SYSTEM+Admins)
└── logs\             ← Logs operativos (SYSTEM+Admins)
```

## Compatibilidad verificada

| Sistema | Verificación |
|---|---|
| Máquina del desarrollador (Windows x64) | Pruebas estáticas + unitarias |
| Windows Server 2022 (VM limpia) | PENDIENTE — bloqueo: VM limpia requerida |
| Windows 11 23H2 (VM limpia) | PENDIENTE |
| Windows Server 2019 (VM limpia) | PENDIENTE |
| Windows Server 2016 (VM limpia) | PENDIENTE |
| Windows 10 LTSC 21H2 (VM limpia) | PENDIENTE |

No declarar compatibilidad sin evidencia de VM limpia. Ver `tasks/checkpoint-2026-09-04c.md`.
