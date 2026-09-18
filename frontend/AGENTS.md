# Instrucciones para Antigravity — Frontend de NEXUS IT

Estas reglas aplican a `frontend/` y complementan `../AGENTS.md`. La raíz y las especificaciones obligatorias siempre prevalecen.

## Misión y alcance

Mantener y mejorar la consola React de NEXUS IT como una interfaz profesional, clara, accesible y responsive. El alcance normal se limita a `frontend/` y sus pruebas.

No modificar `backend/`, `agent/`, `infra/` ni migraciones salvo que la tarea sea explícitamente full-stack. Si falta un contrato, documentarlo; no inventar endpoints. Nunca modificar `.obsidian`.

## Lectura obligatoria

1. `../AGENTS.md`
2. `../Automatizacion/NEXUS IT.md`
3. `../Automatizacion/docs/Seguridad.md`
4. Secciones aplicables de `../Automatizacion/docs/Requisitos.md`
5. `../Automatizacion/docs/Arquitectura.md`
6. `../Automatizacion/docs/Antigravity-Frontend.md`
7. `../tasks/todo.md` y el checkpoint más reciente de `../tasks/`

## Estado vigente

- Frontend implementado con React 18, TypeScript 5, Vite, Lucide, CSS propio por tokens y Vitest.
- Consume `/api/v1` mediante cliente tipado; OpenAPI generado por FastAPI es autoritativo.
- Existen dashboard, dispositivos, telemetría/inventario, alertas, tickets, acciones cerradas, DLQ, administración, auditoría y portal de usuario.
- `RemoteScreenViewer` y `WebTerminalView` son prototipos visuales locales. No reciben video, no controlan equipos y no ejecutan comandos. Toda UI y documentación debe etiquetarlos como demostración.
- La política de seguridad prohíbe consola o shell remota y comandos libres. La UI operativa solo puede solicitar acciones del catálogo cerrado publicado por backend.
- Resultados actuales de tests, typecheck, build y auditoría se registran en el checkpoint; no reutilizar cifras históricas como prueba vigente.

## Tecnología y límites

- TypeScript estricto, componentes funcionales y lockfile reproducible.
- Preferir CSS moderno, variables/tokens y componentes existentes antes de añadir una librería UI.
- No guardar sesión, CSRF, permisos, credenciales o datos sensibles en `localStorage` o `sessionStorage`.
- No usar `dangerouslySetInnerHTML` con contenido no confiable.
- Nunca incluir secretos, tokens reales ni datos personales en fixtures, URL, analytics o logs.
- Datos simulados y prototipos deben llevar una etiqueta visible y copy que no prometa conectividad inexistente.

## Autenticación y cliente HTTP

- Base `/api/v1`; llamadas autenticadas con `credentials: "include"`.
- Cookie de sesión `__Host-nexus_session`, `HttpOnly`, `Secure`, `SameSite=Lax`; JavaScript no la lee.
- Mutaciones copian `__Host-nexus_csrf` a `X-CSRF-Token`.
- Nunca enviar `organization_id` libre para autorizar recursos.
- `401`: sesión ausente o expirada. `403`: permiso insuficiente. `429`: respetar `Retry-After`.
- Errores visibles usan contrato seguro y `error_id` cuando exista; nunca muestran trazas o cuerpos internos.
- Evitar reintentos automáticos de mutaciones no idempotentes.

## Tiempo real

- `/api/v1/ws/telemetry` usa cookie de sesión y `Origin`; no poner tokens en URL.
- Reconexión con backoff, jitter, límite y fallback controlado; nunca buffers ilimitados.
- Mostrar datos parciales o desactualizados con estado explícito.
- No reutilizar este WebSocket de telemetría como transporte de pantalla, teclado, terminal o shell.

## Diseño, copywriting y accesibilidad

- Aplicar `design-taste-frontend` y `high-end-visual-design`: consola sobria, anti-genérica, jerarquía clara y densidad útil.
- Aplicar `copywriting`: textos breves, precisos y basados en capacidades comprobadas.
- Mantener temas claro/oscuro, tokens semánticos, skeleton, vacío, error, permiso denegado y estado desactualizado.
- Evitar gradientes genéricos, glassmorphism excesivo y animación ornamental.
- Objetivo WCAG 2.2 AA: teclado completo, foco visible, contraste, semántica, nombres accesibles, targets de 44 × 44 px y `prefers-reduced-motion`.
- Acciones destructivas muestran confirmación y el recurso exacto afectado.
- Acciones remotas operativas solo presentan el catálogo cerrado y parámetros definidos por OpenAPI.

## Superficies implementadas y contratos

- Auth: login, selección de organización, perfil, recuperación y logout.
- Dispositivos: ciclo de vida, asignaciones, tokens e inventario.
- Métricas: telemetría, estados y operación DLQ.
- Alertas y reglas.
- Help Desk: tickets, comentarios, estados, adjuntos y eliminación confirmada con modal.
- Administración: usuarios, permisos, roles y auditoría.
- Acciones remotas: solicitud, aprobación y seguimiento del catálogo cerrado.
- Portal de usuario: estado del equipo y tickets dentro de sus permisos.

Consultar OpenAPI antes de fijar DTO. Los estados backend son autoritativos y no deben suavizarse con etiquetas ambiguas.

## Pruebas y forma de trabajo

- Antes de editar, leer archivos y pruebas relacionados y buscar un patrón existente.
- Cubrir cliente API, CSRF, errores, estados 401/403/429, loading/vacío/error y el comportamiento modificado.
- Verificar teclado, responsive y navegador real cuando esté disponible.
- Mantener `frontend/README.md` alineado.

```powershell
Push-Location frontend
npm run typecheck
npm test
npm run build
npm audit
Pop-Location
```

Un corte termina solo si consume contratos reales o fixtures claramente marcadas, no expone secretos, supera las verificaciones aplicables y documenta toda limitación vigente.
