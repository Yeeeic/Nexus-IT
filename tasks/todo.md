# Tareas: Backend y Monitoreo NEXUS IT

## Tarea 1: Reconciliar contratos y dependencias

**Criterios de aceptación:**

- [x] Roadmap alineado con `Requisitos.md` para identidad global, tokens HMAC y rutas vigentes.
- [x] Dependencias nuevas justificadas, oficiales, fijadas y auditadas.

**Verificación:** revisión documental, instalación reproducible y `pip-audit`.

**Dependencias:** ninguna.
**Archivos:** `Automatizacion/docs/Roadmap.md`, archivos de requisitos Python.
**Tamaño:** mediano.

## Tarea 2: Configuración y contraseñas

**Criterios de aceptación:**

- [x] Configuración falla de forma segura si faltan secretos obligatorios.
- [x] Hash y verificación Argon2id cubiertos por pruebas, incluida contraseña incorrecta.
- [x] Ningún secreto aparece en representaciones ni errores de configuración.

**Verificación:** prueba enfocada RED/GREEN y suite backend.
**Dependencias:** tarea 1.
**Archivos:** `backend/app/core/config.py`, `backend/app/auth/passwords.py`, pruebas unitarias.
**Tamaño:** mediano.

## Tarea 3: Persistencia de identidad, RBAC y sesiones

**Criterios de aceptación:**

- [x] Migraciones reversibles con usuarios globales, membresías, roles, permisos y sesiones.
- [x] Relaciones tenant incluyen `organization_id` y RLS está forzado en el esquema.
- [x] Acceso cruzado y rol runtime privilegiado son rechazados.

**Verificación:** upgrade/downgrade Alembic y 15 pruebas PostgreSQL negativas con RLS real.
**Dependencias:** tarea 2.
**Archivos:** Migraciones Alembic (`20260824_0001` a `20260825_0020`) y pruebas de infraestructura.
**Tamaño:** mediano.

## Punto de control A

- [x] Suite unitaria completa pasa.
- [x] Suite PostgreSQL pasa en Docker (15/15 pruebas RLS aprobadas).
- [x] Auditoría de dependencias limpia o excepciones documentadas.

## Tarea 4: Login y sesión versionados

**Criterios de aceptación:**

- [x] Entrada estricta y salida sin campos sensibles.
- [x] Respuesta uniforme para usuario inexistente, contraseña incorrecta y cuenta bloqueada.
- [x] Cookie segura emitida solo tras autenticar y seleccionar una membresía autorizada.
- [x] Endpoint `GET /api/v1/auth/me` con datos de perfil, permisos y organizaciones disponibles.

**Verificación:** pruebas API funcionales y de abuso.
**Dependencias:** tarea 3.
**Tamaño:** mediano.

## Tarea 5: CSRF, rate limiting y revocación

**Criterios de aceptación:**

- [x] Mutaciones con cookie rechazan CSRF ausente o inválido.
- [x] Los tres límites de login y el bloqueo temporal están probados.
- [x] Una sesión revocada pierde acceso inmediatamente y queda auditada.

**Verificación:** pruebas API, Redis y concurrencia.
**Dependencias:** tarea 4.
**Tamaño:** mediano.

## Punto de control B

- [x] Suite completa con PostgreSQL/Redis reales sin pruebas omitidas (290/290 pruebas pasando el 2026-08-25).
- [x] Contrato OpenAPI y esquemas Pydantic V2 validados.
- [x] Escaneo de secretos y dependencias aprobado.
- [x] Controles aplicables de `Seguridad.md` comprobados y estado del proyecto actualizado.

## Tarea 6: Restablecimiento de contraseña

**Criterios de aceptación:**

- [x] Token opaco de 256 bits almacenado solo como HMAC-SHA-256 con pepper.
- [x] Consumo único con bloqueo de fila, comparación constante y transacción atómica.
- [x] Cambio de contraseña revoca sesiones y demás tokens pendientes.
- [x] Confirmación versionada, validación estricta, rate limiting y errores uniformes.
- [x] Solicitud anti-enumeración y entrega segura del enlace por canal configurado.
- [x] Concurrencia y rollback comprobados contra PostgreSQL real.

## Tarea 7: Ingesta de métricas, Worker supervisado, Alertas y WebSocket

**Criterios de aceptación:**

- [x] Agente retiene lotes locales con HTTP 202 hasta confirmar estado `PROCESSED`.
- [x] Worker supervisado `MetricBatchWorker` con escaneo multiempresa bajo RLS y concurrency `SKIP LOCKED`.
- [x] Motor de reglas de alerta con ventanas de persistencia, deduplicación y notificación TLS SMTP / WebSocket.
- [x] Implementar particiones diarias UTC y migración desde la partición default mediante `20260830_0023`.
- [x] Implementar retención de 14 días raw, 90 días horarios y 365 días diarios mediante mantenimiento serializado.
- [x] Validar `20260830_0022` y `20260830_0023` con upgrade/downgrade/upgrade y pruebas PostgreSQL/RLS reales.
- [x] Implementar outbox durable con reintentos idempotentes para eliminación física de adjuntos (`20260831_0024`).
- [x] Conectar inventario del sistema y ejecución de acciones Ed25519 con catálogo cerrado al runner del agente.
- [x] Almacenamiento seguro de adjuntos conectado al runtime y volumen privado Docker.

## Tarea 8: Estrategia de Copias de Seguridad y PITR

**Criterios de aceptación:**

- [x] Script `backup-logical.sh` con cifrado AES-256-GCM y preservación de roles/RLS.
- [x] Script `pitr-archive-wal.sh` para archivado continuo e idempotente de WAL.
- [x] Script `pitr-restore.sh` para recuperación Point-In-Time verificable.
- [x] Runbook `BACKUP-AND-RESTORE.md` con matriz de validación post-restauración.
- [x] Ensayo PITR aislado del 2026-09-04: RPO 11 s, RTO 7 s, RLS/FK/rol runtime y limpieza verificados.
- [ ] Conectar `archive_mode`, `archive_command`, base backups y almacenamiento WAL al despliegue real.
- [ ] Repetir restauración completa en staging/producción y conservar evidencia de RPO/RTO; el ensayo aislado no sustituye validación operativa.

## Tarea 9: Integración Full-Stack, Contratos OpenAPI, Frontend y CI/CD

**Criterios de aceptación:**

- [x] Auditoría OpenAPI de FastAPI como fuente autoritativa e Incompatibility Matrix resuelta.
- [x] Endpoints backend completados (`GET /permissions`, `GET /alert-rules`, `GET /tickets/{id}`, `GET /devices/{id}/actions` con sesión).
- [x] Tipos TypeScript y clientes API sincronizados con DTOs reales y wrappers `{ items, next_cursor }`.
- [x] Vistas de Frontend adaptadas con soporte de paginación, modales de acción/token/aprobación, diseño de alta gama y copywriting profesional.
- [x] Evidencia verificada el 2026-09-04: 321 pruebas backend/agente + 34 pruebas de infraestructura PostgreSQL/Docker + 28 pruebas frontend + Typecheck + Build de producción + auditorías limpias.
- [x] Ensayo E2E integrado repetido dos veces: 13 controles de API, worker, agente real, Ed25519, replay y revocación.
- [x] Dockerfile multi-stage de frontend, configuración segura NGINX con cabeceras HTTP y pipeline CI/CD en GitHub Actions.

## Tarea 10: Alineación de instrucciones, seguridad y estado

**Criterios de aceptación:**

- [x] `AGENTS.md`, `backend/AGENTS.md` y `frontend/AGENTS.md` comparten jerarquía y checkpoint vigente.
- [x] Documentación para Antigravity refleja contratos y limitaciones actuales.
- [x] Visor y terminal etiquetados como prototipos sin conexión ni ejecución real.
- [x] Regresión RLS de `0018` corregida de forma aditiva mediante `0019` y `0020`, con permisos mínimos por columna.
- [x] Upgrade/downgrade/upgrade y 21 pruebas PostgreSQL/RLS reales aprobados en Docker.
- [x] Resolver en código retención y particionado sin contradecir `Requisitos.md`.
- [x] Aprobar retención, particionado y administración de usuarios contra PostgreSQL real.
- [ ] Completar recorrido autenticado desde navegador; E2E API/agente ya verificado en Compose.

## Tarea 11: Orquestación multiagente y memoria coherente

**Criterios de aceptación:**

- [x] Definir a Antigravity como orquestador y separar Research, Architect, Coding/Codex y revisión independiente.
- [x] Documentar Graph Loop, contrato de entrega, puerta de commit y memoria de Obsidian.
- [x] Alinear la bóveda con `20260831_0024`, la validación PostgreSQL, la outbox y el runner conectado.
- [x] Mantener pantalla y terminal como prototipos y la prohibición absoluta de shell libre.
- [ ] Crear commit aislado cuando el árbol de trabajo permita separar estos cambios de trabajo previo.

## Tarea 12: Corrección y validación de agent_config.example.json

**Criterios de aceptación:**

- [x] `agent/agent_config.json` excluido por `.gitignore` línea 3 (verificado con `git check-ignore`).
- [x] `agent/agent_config.example.json` no ignorado por Git (verificado con `git check-ignore` exit 1).
- [x] Ejemplo actualizado con los 5 campos que acepta `load_config()`: `server_url`, `device_id`, `hostname`, `inventory_interval`, `public_keys`.
- [x] Validación programática contra `allowed` de `load_config()` pasa sin campos desconocidos.
- [x] `pytest.ini` revisado: configuración coherente (`--basetemp=.pytest_temp`, `testpaths=tests`); archivo no rastreado pendiente de incluir en el commit del diff completo.
- [x] 298 pruebas unitarias/backend pasan (sin DB real; `NEXUS_RUN_DB_TESTS` no activo).
- [x] 28 pruebas frontend pasan; typecheck limpio.
- [x] `git diff --check` solo emite warnings LF→CRLF de `.gitattributes`; sin trailing whitespace ni marcadores de conflicto.
- [x] `.obsidian` sin cambios confirmado.

**Verificación:** `pytest tests/agent/ tests/backend/ -q` → 298 passed 7.20s; `npm test -- --run` → 28 passed; `tsc --noEmit` → sin errores.
**Pendiente:** `git add` y commit diferidos hasta revisión del diff completo (Tarea 11).

## Tarea 13: Agente Windows — producción segura y verificable

**Criterios de aceptación:**

- [x] Secretos eliminados de disco: token real, UUID de despliegue, clave pública Ed25519 de despliegue, IP de servidor.
- [x] `agente-windows/iniciar-agente.bat` saneado — sin secretos, redirige al instalador.
- [x] `agente-windows/agent/agent_config.json` reemplazado por plantilla sin secretos.
- [x] `agente-windows/LEEME.txt` reemplazado sin IP real.
- [x] `agente-windows/BUILD.md` — build verificable con hash Python 3.13.3 y dependencias fijadas; no reproducible byte a byte.
- [x] `agente-windows/INSTALL.md` — guía completa install/update/rollback/uninstall.
- [x] `agente-windows/build-package.ps1` — script de build: descarga Python embeddable, instala cryptography+pywin32, copia agente canónico, genera MANIFEST.sha256 + SBOM.json.
- [x] `agente-windows/service/nexus_agent_service.py` — Windows Service real (pywin32), token desde DPAPI, sin shell, catálogo cerrado, stop limpio.
- [x] `agente-windows/service/nexus-agent-ctl.ps1` — install/start/stop/status/update/rollback/uninstall; ACL NTFS; DPAPI; sc.exe; reinicio automático tras fallos.
- [x] `frontend/public/install-agent.ps1` corregido: descarga ZIP completo, SHA-256, verificación de contenido, sin `interval`, HTTP rechazado en no-loopback, limpieza tras error.
- [x] `Automatizacion/docs/Agente-y-Telemetria.md` actualizado: sin Win7/8/8.1, Windows Service, matriz de compatibilidad honesta.
- [x] Contratos Windows y agente pertinentes → 114 passed, 3 skipped al 2026-09-13.
- [ ] Repetir suite backend/infra completa con PostgreSQL/Docker antes del cierre global; 410 passed, 22 skipped es evidencia histórica del 2026-09-04.
- [x] `git diff --check` — solo warnings LF→CRLF, sin trailing whitespace.
- [x] `.obsidian` no fue tocado en este cierre; `Automatizacion/.obsidian/graph.json` ya tenía una modificación previa.
- [x] Revisión independiente aprobada (5 ejes: correctitud, legibilidad, arquitectura, seguridad, rendimiento).
- [ ] SIGN_PENDING: certificado Authenticode EV Code Signing — bloqueo externo.
- [ ] VM limpia x sistema declarado compatible — bloqueo externo.
- [ ] Revocación del token de despliegue anterior — requiere acceso del usuario a la consola NEXUS IT.
- [ ] Limpiar o adoptar de forma explícita los residuos locales `C:\ProgramData\NexusIT\Agent` (`agent.db`, `actions.sqlite3`); el servicio no está instalado.
- [ ] Resolver 2 vulnerabilidades moderadas de herramientas de desarrollo (`vitest`/`@vitest/mocker`) mediante una actualización mayor probada; producción (`npm audit --omit=dev`) está en 0.
- [ ] Medir CPU/RAM y validar arranque, reinicio, actualización y rollback en VMs limpias.
- [ ] Implementar canal central autenticado de actualización y rollback.
- [ ] `git add` y commit diferidos hasta revisión del diff completo con el resto del árbol de trabajo.

**Verificación vigente (2026-09-13):** `pytest tests/agent tests/infra/test_windows_agent_package.py tests/infra/test_agent_installers.py` → 114 passed, 3 skipped; frontend → 29 passed, typecheck/build verdes; auditoría Windows y producción frontend → 0 vulnerabilidades conocidas. ZIP SHA-256 `a447aad4d54c541aca7966dd9eab07116ac4fdcf38514131f824332fdc98f534`; EXE SHA-256 `2e56971dd6b610667329f42f4979e83cb1f3524fc82af899e41511512edf518e` y `NotSigned`. Revisión independiente: aprobada, sin P0/P1.

**Estado del agente Windows:** implementación y revisión de código cerradas al 2026-09-13; aún no apto para distribución de producción hasta completar Authenticode, VMs limpias/SCM-E2E, métricas CPU/RAM, revocación del token histórico y canal central de actualización. El ZIP es verificable, no reproducible byte a byte.


**Estado global:** MVP integrado. Suites verdes al 2026-09-04 sesión 2: 298 pruebas unitarias/backend (sin Docker) + 28 frontend, typecheck limpio. Evidencia histórica: 321 backend/agente + 34 infraestructura PostgreSQL/Docker + E2E API/agente repetido dos veces + TLS local verificado al 2026-09-04 sesión 1. Migraciones hasta `20260831_0024`. Pendiente: commit del árbol completo, recorrido navegador, staging PITR, rotación de credenciales históricas, almacenamiento WAL/adjuntos operativo.
