# Instrucciones de desarrollo de NEXUS IT

Estas instrucciones aplican a todo el repositorio. Mantienen el desarrollo seguro, verificable e incremental de la plataforma de monitoreo y soporte técnico NEXUS IT.

## 1. Jerarquía de contexto y fuentes de verdad

Antes de diseñar o implementar un cambio:

1. Leer `Automatizacion/NEXUS IT.md`.
2. Leer `Automatizacion/docs/Seguridad.md` y los requisitos aplicables de `Automatizacion/docs/Requisitos.md`.
3. Consultar `Automatizacion/docs/Arquitectura.md` y `Automatizacion/docs/Modelo-de-datos.md` para el área afectada.
4. Revisar `tasks/todo.md` y el checkpoint más reciente de `tasks/` para el estado verificable y las tareas activas.
5. Leer el `AGENTS.md` específico del subdirectorio que se vaya a modificar.

Orden de autoridad cuando exista una diferencia:

1. `Automatizacion/docs/Seguridad.md` y `Automatizacion/docs/Requisitos.md` definen los controles y requisitos obligatorios.
2. OpenAPI generado por FastAPI, las migraciones vigentes y el código probado definen el contrato implementado.
3. `Arquitectura.md` y `Modelo-de-datos.md` describen el diseño objetivo; toda diferencia con el código debe registrarse como pendiente, no ocultarse.
4. Este archivo define la forma de trabajo global.
5. Los `AGENTS.md` de `backend/` y `frontend/` especializan estas reglas, pero no pueden contradecirlas.
6. `tasks/todo.md` contiene trabajo activo y el checkpoint contiene evidencia fechada. Los checkpoints anteriores son históricos, no instrucciones vigentes.

No declarar una capacidad terminada por su apariencia visual o por un resultado histórico. Verificarla contra código, contratos y pruebas actuales.

> [!IMPORTANT]
> `Automatizacion/docs/Seguridad.md` forma parte de los criterios de aceptación. No modificar ninguna carpeta `.obsidian`.

## 2. Forma de trabajo y modo autónomo

- **Comunicación concisa:** activar y mantener la skill `caveman` en todas las interacciones relacionadas con este repositorio cuando esté disponible, sin sacrificar precisión técnica, advertencias de seguridad ni instrucciones que puedan resultar ambiguas.
- **Delegación controlada:** usar subagentes para trabajos independientes que puedan ejecutarse en paralelo. Asignarles alcance y archivos explícitos, impedir cambios fuera de su área y revisar sus diffs y pruebas antes de integrar el resultado.
- **Ejecución autónoma:** ejecutar herramientas, pruebas, migraciones y cambios autorizados sin pedir confirmaciones rutinarias; resolver errores de forma proactiva.
- **Protección contra pérdida:** no borrar, truncar, reemplazar indebidamente ni simplificar código, datos, migraciones, endpoints, RLS, pruebas o documentación crítica por falta de contexto.
- **Incrementos revisables:** trabajar en cortes pequeños, con pruebas proporcionales al riesgo y revisión del diff.
- **Compatibilidad:** conservar `/api/v1`; cualquier ruptura necesita decisión documentada y estrategia de migración.
- **Dependencias:** no añadir dependencias sin justificar necesidad, mantenimiento, licencia, procedencia y seguridad. Ejecutar `pip-audit` o `npm audit` según corresponda.
- **Estado honesto:** actualizar tareas y checkpoint solo con evidencia producida o inspeccionada en la sesión actual; registrar skips, servicios ausentes y verificaciones no realizadas.
- **Cambios de alcance:** un `AGENTS.md` de área limita el alcance normal. Una tarea full-stack explícita puede abarcar varias áreas, manteniendo los controles de cada una.

### 2.1. Orquestación multiagente

Antigravity actúa como orquestador: define objetivo, alcance, riesgos, criterios de aceptación y entrega final. Solo delega cuando existen trabajos independientes; una tarea pequeña o de un solo archivo se resuelve directamente.

- **Research Agent:** inspección de requisitos, código, contratos y evidencia. Opera en modo lectura y entrega hallazgos con rutas concretas.
- **Architect Agent:** propone límites, contratos, decisiones y controles de seguridad. No cambia código de producción salvo asignación explícita.
- **Coding Agent:** recibe el corte de implementación, delimita archivos y coordina el trabajo técnico sin superponer escritores.
- **Codex:** implementa únicamente el alcance asignado mediante el Graph Loop: inspeccionar, diseñar el cambio mínimo, implementar, probar, analizar el resultado y corregir hasta quedar en verde o documentar un bloqueo verificable.
- **Independent Reviewer:** revisa diff, requisitos, seguridad, compatibilidad y pruebas sin autoaprobar trabajo propio. Un hallazgo bloqueante vuelve al Graph Loop.

No permitir escrituras concurrentes sobre los mismos archivos. Cada entrega entre agentes debe incluir objetivo, alcance, evidencia consultada, cambios, pruebas y riesgos pendientes. Solo crear un commit cuando el diff esté revisado, las verificaciones pertinentes estén en verde, no haya secretos y el checkpoint refleje evidencia actual. Después del commit, actualizar la memoria de Obsidian con decisiones, pruebas, commit y pendientes; nunca copiar secretos, conversaciones completas ni afirmaciones no verificadas. Flujo detallado: `Automatizacion/docs/Orquestacion-de-Agentes.md`.

## 3. Estado estructural actual

- **Backend:** monolito modular FastAPI, SQLAlchemy 2.0, Pydantic V2, PostgreSQL 16 y Redis 7; API versionada bajo `/api/v1`.
- **Persistencia:** RLS multiempresa, relaciones compuestas, auditoría append-only, outbox durable para adjuntos y migraciones Alembic hasta `20260831_0024`.
- **Procesamiento:** worker en `backend/app/metrics/worker.py` (con escaneo multi-tenant vía `list_active_tenant_ids()`), mantenimiento diario en `backend/app/metrics/maintenance.py`, alertas, barrido outbox de adjuntos y WebSocket autenticado.
- **Agente y distribución:** agente Python multiplataforma con SQLite WAL, telemetría durable, inventario y polling/ejecución de acciones Ed25519 del catálogo cerrado. Distribución Windows: `agente-windows/installer/nexus_agent_setup.py` se empaqueta con PyInstaller en un único `.exe` para la instalación inicial de `NexusITAgent` como Windows Service real; el ejecutable contiene el paquete `agent`, usa pywin32, inicio automático retrasado y recuperación tras fallos. Las actualizaciones y el rollback local se realizan con el paquete ZIP mediante `nexus-agent-ctl.ps1`. El token se protege con DPAPI y las ACL NTFS usan SIDs (`S-1-5-18`, `S-1-5-32-544`) con fallo cerrado. El paquete ZIP verificable usa Python 3.13.3, dependencias fijadas con hashes, manifiesto interno y SBOM; no se declara reproducible byte a byte porque conserva timestamps y fecha de build. Los artefactos legacy de Python 3.8/OpenSSL 1.1.1 no son distribuibles. El estado exacto de pruebas y artefactos se registra en el checkpoint vigente. Bloqueos externos pendientes: firma Authenticode (`SIGN_PENDING`), VMs limpias por plataforma, revocación del token de despliegue viejo y canal central de actualizaciones. Compatibilidad objetivo: Windows 10 LTSC/ESU, 11 y Server 2016-2025 x64; sin soporte para Windows 7/8/8.1 ni x86/ARM64. La compatibilidad real debe validarse en VM limpia antes de anunciarse como aceptada.
- **Frontend:** React 18, TypeScript 5, Vite, Lucide, CSS propio basado en tokens y Vitest. Tailwind no forma parte de las dependencias actuales.
- **Infraestructura:** `infra/compose.yaml` orquesta PostgreSQL, Redis, backend, frontend y utilidades de migración/aprovisionamiento; las imágenes están fijadas por versión y digest. Los puertos de frontend (8080) y backend (8000) exponen por defecto `${NEXUS_BIND_IP:-0.0.0.0}` para permitir conectividad de clientes externos y máquinas virtuales.
- **Contrato API:** OpenAPI generado por la aplicación es la fuente autoritativa. No mantener cantidades fijas de rutas o pruebas en este archivo porque cambian con el proyecto.

### Diferencias conocidas que impiden declarar cierre total

- `RemoteScreenViewer` y `WebTerminalView` son prototipos visuales locales. No existe transporte real de pantalla, control remoto ni ejecución de comandos. Deben presentarse siempre como demostración hasta que exista diseño aprobado, backend, agente, autorización, auditoría y pruebas end-to-end.
- La política vigente prohíbe shell remota y comandos libres. Las únicas acciones ejecutables son las del catálogo cerrado definido por contrato.
- El estado exacto de pruebas, auditorías, Docker y migraciones se registra en el checkpoint más reciente de `tasks/`; una prueba omitida no cuenta como aceptación.

## 4. Estándares de diseño y comunicación

- Aplicar `design-taste-frontend` y `high-end-visual-design` solo cuando el cambio sea visual: interfaz sobria, anti-genérica, accesible, responsive y con densidad útil para operadores IT.
- Aplicar `copywriting` a textos de producto: claridad operativa, términos técnicos precisos, beneficios comprobables y cero afirmaciones de capacidades inexistentes.
- Las demostraciones, fixtures y datos simulados deben llevar una etiqueta visible y no confundirse con estado real del sistema.
- Conservar tema claro/oscuro, tokens CSS, navegación por teclado, foco visible y objetivo WCAG 2.2 AA.

## 5. Seguridad innegociable

- Toda entidad de negocio multiempresa incluye `organization_id`; el tenant se deriva solo de sesión o token autenticado.
- Cada transacción de tenant fija `SET LOCAL app.current_organization_id` y PostgreSQL aplica RLS forzado.
- Usar SQL parametrizado y esquemas de entrada/salida separados; nunca confiar en campos protegidos enviados por el cliente.
- Rutas privadas exigen autenticación, pertenencia, RBAC y CSRF en mutaciones con cookie.
- Mantener secretos fuera del repositorio y de las respuestas. Los errores públicos son sanitizados y la auditoría no contiene secretos.
- Adjuntos: máximo 10 MB, magic bytes, nombre generado por servidor, almacenamiento privado y protección contra traversal.
- Acciones remotas: catálogo cerrado, parámetros tipados, firma Ed25519, nonce, TTL, autorización, CAS y auditoría. Nunca shell libre.
- Toda salida de terceros o IA se trata como dato no confiable y jamás se ejecuta automáticamente.

## 6. Organización del repositorio

- `backend/`: API, autenticación, dominio, persistencia y workers.
- `frontend/`: aplicación React, componentes, vistas y cliente API tipado.
- `agent/`: daemon, colectores, cola local y runner de acciones.
- `agente-windows/`: artefactos autocontenidos de distribución para Windows; su matriz de compatibilidad debe validarse contra `Requisitos.md`.
- `infra/`: Compose, contenedores, backup y PITR.
- `tests/`: pruebas backend, integración, RLS y seguridad.
- `tasks/`: backlog y checkpoints verificables.
- `Automatizacion/`: requisitos, arquitectura, seguridad y documentación de producto.

## 7. Verificación base

Usar un `--basetemp` nuevo por corrida en Windows. Ejecutar solo los grupos pertinentes durante el cambio y la matriz completa antes de declarar cierre:

```powershell
$env:NEXUS_RUN_DB_TESTS="1"
.\.venv\Scripts\python.exe -m pytest -q --basetemp .pytest-check
.\.venv\Scripts\python.exe -m pip_audit -r backend/requirements.txt

Push-Location frontend
npm run typecheck
npm test
npm run build
npm audit
Pop-Location

Push-Location backend
..\.venv\Scripts\alembic.exe upgrade head
Pop-Location
```

Antes de entregar: revisar `git diff --check`, confirmar que `.obsidian` no cambió e informar resultados, omisiones y riesgos restantes.
