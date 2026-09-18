# Instrucciones para Antigravity — Backend de NEXUS IT

Estas reglas aplican a `backend/` y complementan `../AGENTS.md`. La raíz y las especificaciones obligatorias siempre prevalecen.

## Misión y alcance

Mantener, completar y verificar el monolito modular FastAPI multiempresa. El alcance normal incluye `backend/`, pruebas relacionadas en `tests/`, infraestructura necesaria en `infra/` y cambios interoperables mínimos en `agent/` cuando el contrato backend-agente lo exija.

No modificar `frontend/` salvo que la tarea sea explícitamente full-stack. Nunca modificar `.obsidian`.

## Lectura obligatoria

1. `../AGENTS.md`
2. `../Automatizacion/NEXUS IT.md`
3. `../Automatizacion/docs/Seguridad.md`
4. Secciones aplicables de `../Automatizacion/docs/Requisitos.md`
5. `../Automatizacion/docs/Arquitectura.md` y `../Automatizacion/docs/Modelo-de-datos.md`
6. `../Automatizacion/docs/Antigravity-Backend.md`
7. `../tasks/todo.md` y el checkpoint más reciente de `../tasks/`

## Estado vigente y fuentes

- Migraciones existentes hasta `20260831_0024`; añadir una nueva migración para cambios posteriores, nunca reescribir una aplicada.
- Aplicación en `backend/app/main.py`; runtime en `backend/app/core/runtime.py`.
- Worker de métricas en `backend/app/metrics/worker.py` (con escaneo multi-tenant seguro vía `list_active_tenant_ids()`); mantenimiento en `backend/app/metrics/maintenance.py` con particiones diarias UTC.
- OpenAPI generado por FastAPI define rutas, DTO y códigos reales. Generarlo y compararlo antes de cambiar contratos.
- Los totales de pruebas, auditorías y disponibilidad de Docker viven únicamente en el checkpoint vigente.
- No existe backend/agente para pantalla remota o terminal web. La política prohíbe shell y comandos libres.

## Arquitectura que debe conservarse

- Python 3.11+, FastAPI, Pydantic V2 y SQLAlchemy 2.0.
- PostgreSQL 16 durable; Redis 7 para rate limiting, Pub/Sub y estado efímero.
- API pública bajo `/api/v1` y límites modulares entre autenticación, administración, dispositivos, métricas, tiempo real y soporte.
- Principal runtime de mínimo privilegio, separado del principal de migración.
- Migraciones reversibles y compatibles; toda excepción requiere decisión documentada.

## Seguridad innegociable

1. Toda entidad tenant usa `organization_id` y relaciones compuestas.
2. El tenant deriva de sesión o token de agente verificado, nunca de datos libres del cliente.
3. Toda transacción tenant usa `SET LOCAL app.current_organization_id`; RLS queda forzado.
4. El rol runtime no es propietario, superusuario ni tiene `BYPASSRLS`.
5. Entradas usan esquemas cerrados y salidas no exponen hashes, secretos, SQL, trazas ni rutas internas.
6. SQL siempre parametrizado.
7. Rutas web privadas exigen sesión, RBAC, pertenencia y CSRF en mutaciones.
8. Agentes usan Bearer tokens rotables; servidor deriva dispositivo y organización.
9. Sesión opaca en cookie `__Host-nexus_session` con `HttpOnly`, `Secure` y `SameSite=Lax`.
10. Login uniforme, Argon2id y límites por correo, IP y par IP/correo.
11. Adjuntos de máximo 10 MB, magic bytes, UUID, almacenamiento privado y confinamiento.
12. Acciones remotas solo por catálogo cerrado, parámetros rígidos, Ed25519, nonce, TTL, CAS y auditoría. Nunca shell libre.
13. Errores públicos sanitizados con `error_id` cuando aplique; detalle solo en logs protegidos.
14. Toda mutación sensible registra actor, organización, fecha y resultado sin secretos.

## Contratos existentes

- Auth: login, contexto, logout, perfil y restablecimiento.
- Administración: usuarios, permisos, roles, asignaciones y auditoría.
- Dispositivos: ciclo de vida, tokens, asignaciones e inventario.
- Métricas: ingesta durable, estados, reintento, reupload, diagnóstico, DLQ, reglas y alertas.
- Soporte: tickets, comentarios, estados, adjuntos y eliminación con auditoría inmutable (`DELETE /api/v1/tickets/{ticket_id}`).
- Acciones: solicitud, aprobación, polling, ack y resultado del catálogo cerrado.
- Tiempo real: `/api/v1/ws/telemetry` autenticado por cookie y `Origin` validado.

No inventar contratos para satisfacer la UI. Diseñar, probar, documentar y regenerar OpenAPI cuando falte uno.

## Pendientes de cierre verificable

1. Ejecutar el despliegue Compose integrado y obtener evidencia end-to-end de enrolamiento, inventario y acciones desde la consola.
2. Revocar y rotar el token eliminado que permanece en el historial Git previo.
3. Validar restauración PITR y objetivos RPO/RTO en staging antes de producción.
4. Adoptar almacenamiento de adjuntos compartido antes de escalar a múltiples réplicas.
5. Mantener cobertura de mantenimiento, RLS, migraciones, carga, concurrencia y recuperación sin contar skips como aprobación.
6. Mantener pantalla remota y terminal fuera del backend mientras no exista una especificación compatible con la prohibición de shell libre.
7. Actualizar tareas y checkpoint solo con resultados actuales.

## Forma de trabajo y verificación

- Revisar el diff antes de editar y preservar trabajo ajeno.
- Para lógica o correcciones: prueba de regresión, cambio mínimo, prueba en verde y revisión de seguridad.
- No instalar dependencias sin evaluación documentada.
- Usar un `--basetemp` nuevo dentro del repositorio en Windows.

```powershell
$env:NEXUS_RUN_DB_TESTS="1"
.\.venv\Scripts\python.exe -m pytest -q --basetemp .pytest-antigravity-backend
.\.venv\Scripts\python.exe -m pip_audit -r backend/requirements.txt
Push-Location backend
..\.venv\Scripts\alembic.exe heads
..\.venv\Scripts\alembic.exe upgrade head
Pop-Location
```

Un cierre válido requiere resultados actuales, servicios reales para las pruebas que los necesitan, cero vulnerabilidades altas/críticas sin excepción y documentación que refleje las limitaciones comprobadas.
