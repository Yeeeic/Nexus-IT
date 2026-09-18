# Checkpoint — 2026-09-13 — cierre técnico del agente Windows

## Resultado

El código, los instaladores y los artefactos del agente Windows quedaron
corregidos y aprobados por revisión independiente dentro del alcance verificable
en esta estación. No se declara listo para producción porque faltan controles
externos y pruebas en VMs limpias.

## Cambios cerrados

- El `.exe` queda limitado a instalación inicial. Rechaza servicio o directorio
  existente y limpia servicio/archivos si una instalación nueva falla.
- El ZIP instala, actualiza y revierte mediante `nexus-agent-ctl.ps1`.
- El backup de actualización recibe ACL para SYSTEM/Administradores, genera
  `BACKUP.sha256` y se verifica antes del rollback.
- Ambos instaladores aceptan únicamente URL con esquema, host y puerto opcional;
  rechazan credenciales, ruta, query y fragmento. HTTP solo se permite en
  loopback con una opción explícita de desarrollo.
- El modo servicio falla cerrado si pywin32 no está disponible.
- Token protegido con DPAPI, configuración no secreta, ACL por SID y catálogo
  cerrado de acciones; no existe shell remota.
- Los instaladores públicos, documentación y UI usan el artefacto y hash actuales.

## Artefactos

| Artefacto | Tamaño | SHA-256 | Estado |
|---|---:|---|---|
| `agente-windows/dist/nexus-agent-setup.exe` | 16,675,413 bytes | `2e56971dd6b610667329f42f4979e83cb1f3524fc82af899e41511512edf518e` | `NotSigned` |
| `agente-windows/nexus-it-agent-windows-x64-1.0.0.zip` | 22,589,104 bytes | `a447aad4d54c541aca7966dd9eab07116ac4fdcf38514131f824332fdc98f534` | manifiesto verificado |
| `frontend/public/nexus-it-agent-windows-x64-1.0.0.zip` | 22,589,104 bytes | `a447aad4d54c541aca7966dd9eab07116ac4fdcf38514131f824332fdc98f534` | coincide con fuente |

El ZIP conserva timestamps y fecha de build: es verificable mediante hashes,
pero no se afirma reproducibilidad byte a byte.

## Evidencia de esta sesión

| Verificación | Resultado |
|---|---|
| Agente + contratos Windows pertinentes | 114 passed, 3 skipped |
| Contratos Windows enfocados | 82 passed, 3 skipped |
| Frontend Vitest | 29 passed |
| Frontend typecheck y build | Verde |
| `pip-audit` del lock Windows | 0 vulnerabilidades conocidas |
| `npm audit --omit=dev` | 0 vulnerabilidades |
| `npm audit` completo | 2 moderadas, solo tooling Vitest; corrección exige salto mayor |
| Parser Windows PowerShell 5.1 | 3 scripts válidos |
| Runtime embebido | imports de agente, cryptography 50.0.1, pywin32 y servicio correctos |
| `git diff --check` | sin errores; solo advertencias LF/CRLF |
| `.obsidian` | no tocado en esta sesión; `graph.json` conserva una modificación previa |
| Revisión independiente | APROBADO; sin P0/P1 |

Los tres skips corresponden a artefactos legacy ausentes y no cuentan como
aceptación de compatibilidad. La suite backend/infra completa no se repitió en
esta sesión; el resultado de 410 passed/22 skipped del 2026-09-04 es histórico.

## Bloqueos antes de producción

1. Firmar el `.exe` y los scripts con Authenticode y verificar la cadena.
2. Probar en VMs limpias de cada plataforma declarada: instalación, SCM,
   reinicio, actualización, rollback y desinstalación.
3. Medir CPU/RAM, estabilidad prolongada y recuperación tras fallos.
4. Revocar el token histórico de despliegue desde la consola NEXUS IT.
5. Implementar el canal central autenticado, versionado y auditable de updates.
6. Resolver o aceptar formalmente las 2 vulnerabilidades moderadas del tooling
   Vitest tras probar la actualización mayor.
7. Decidir si se conservan o eliminan `C:\ProgramData\NexusIT\Agent\agent.db`
   y `actions.sqlite3`; actualmente no existe el servicio `NexusITAgent`.

No se ejecutó una instalación real ni se alteró `C:\ProgramData` en esta sesión.
No se creó commit debido a que el árbol contiene cambios previos de varias áreas.
