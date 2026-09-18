# Plan de implementación: autenticación y sesiones (incremento 03)

## Resumen

Continuar desde la base multiempresa ya registrada en Git con un primer flujo autenticado, versionado bajo `/api/v1`, que derive la organización desde membresías autorizadas y nunca desde datos libres del cliente. El trabajo se entregará en cortes pequeños, probados y reversibles.

## Estado de partida verificado

- La prueba unitaria de salud pasa.
- La auditoría de dependencias runtime no reporta vulnerabilidades conocidas.
- Las pruebas PostgreSQL/RLS existen, pero no pudieron ejecutarse porque Docker no está disponible en el equipo.
- Los incrementos 01 y 02 están registrados en Git; el siguiente incremento es autenticación.

## Decisiones de arquitectura

- FastAPI seguirá como monolito modular; los contratos públicos se versionan bajo `/api/v1`.
- Las contraseñas usarán Argon2id y los esquemas Pydantic rechazarán campos adicionales.
- Las sesiones serán opacas, persistidas en servidor y entregadas mediante cookies `HttpOnly`, `Secure` y `SameSite=Lax`; no se usará `localStorage`.
- El `organization_id` se derivará de una membresía activa después de autenticar al usuario.
- PostgreSQL aplicará RLS como defensa en profundidad y Redis se limitará al control efímero de frecuencia.

## Alcance

1. Reconciliar el Roadmap con los requisitos canónicos vigentes.
2. Introducir configuración validada y primitivas de contraseña con pruebas.
3. Crear la migración de usuarios, roles, membresías y sesiones con RLS/FK compuestas.
4. Implementar el contrato de login y sesión con errores seguros y cookies endurecidas.
5. Incorporar rate limiting, CSRF, revocación y pruebas de abuso.

Fuera de alcance: enrolamiento de agentes, ingesta de métricas, acciones remotas y frontend.

## Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Fuga entre organizaciones | Alto | Derivación de tenant desde membresía, RLS forzado, FKs compuestas y pruebas negativas. |
| Enumeración o fuerza bruta | Alto | Respuestas uniformes, verificación Argon2id ficticia, tres capas de rate limiting y bloqueo temporal. |
| Robo/fijación de sesión | Alto | IDs opacos regenerados, hash en servidor, cookies seguras, expiración y revocación. |
| CSRF | Alto | Token CSRF asociado a sesión y validación en mutaciones. |
| Dependencia o patrón obsoleto | Medio | Verificación contra documentación oficial y lockfile reproducible. |
| Integración RLS sin ejecutar localmente | Medio | Mantener la prueba marcada y ejecutarla en CI/Docker antes de cerrar el incremento. |

## Estrategia de pruebas

- RED/GREEN unitario para configuración, normalización y Argon2id.
- Integración PostgreSQL para RLS, FKs compuestas, roles sin `BYPASSRLS` y limpieza de contexto.
- Pruebas API para validación estricta, cookies, errores uniformes, revocación y CSRF.
- Pruebas de abuso: tenant ajeno, rol insuficiente, campos protegidos, fuerza bruta y concurrencia.
- Auditoría de dependencias y búsqueda de secretos antes de cada punto de control.

## Condición de cierre

El incremento no se considerará terminado mientras las pruebas PostgreSQL/RLS sigan sin ejecutarse o exista una excepción de seguridad no documentada.
