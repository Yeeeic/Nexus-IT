# NEXUS IT — Consola Web Frontend

Interfaz de usuario web moderna, accesible y de alta gama para la plataforma de monitoreo y mesa de ayuda multiempresa **NEXUS IT**.

## Tecnologías Utilizadas

- **Framework:** React 18 con TypeScript estricto.
- **Herramienta de Construcción:** Vite 6.
- **Iconografía:** Lucide React.
- **Estilos & Diseño:** Tokens CSS nativos (`tokens.css` y `index.css`), tema claro/oscuro dinámico y componentes sin dependencias UI pesadas.
- **Pruebas:** Vitest con `@testing-library/react` y `jsdom`.

## Principios de Arquitectura y Seguridad

1. **Aislamiento Multi-Tenant:**
   - La organización activa se deriva exclusivamente de la sesión autenticada (`GET /api/v1/auth/me`).
   - El selector de contexto permite alternar entre membresías autorizadas sin enviar parámetros libres.
2. **Seguridad de Sesiones y CSRF:**
   - Autenticación mediante cookies de host seguras (`__Host-nexus_session`).
   - Inyección automática de token CSRF (`X-CSRF-Token`) en todas las mutaciones (`POST`, `PUT`, `PATCH`, `DELETE`).
   - Prohibido el uso de `localStorage` o `sessionStorage` para credenciales, tokens o permisos.
3. **Telemetría y Tiempo Real:**
   - Conexión WebSocket en `/api/v1/ws/telemetry` con reconexión exponencial y jitter.
   - Gráficas SVG accesibles con modo alternativo tabular para lectores de pantalla.
4. **Remediación Segura:**
   - Catálogo cerrado de acciones remotas (`system.reboot`, `service.restart`, `process.kill`, `diagnostics.collect`) firmadas asimétricamente con Ed25519 en servidor.

## Módulos y Pantallas

- **Dashboard:** KPIs en vivo, gráficas de uso de CPU/RAM, alertas críticas y tickets de soporte recientes.
- **Dispositivos:** Inventario de hardware, software, interfaces de red, servicios del sistema y generación de tokens de máquina.
- **Alertas & Umbrales:** Monitor de alertas abiertas/resueltas y creador de reglas de umbral con persistencia anti-flapping.
- **Mesa de Ayuda (Help Desk):** Ciclo de vida de tickets, notas internas protegidas y carga de adjuntos validados por magic bytes.
- **Consola de Acciones Remotas:** Solicitud, aprobación de dos factores y seguimiento de ejecución.
- **Monitor DLQ:** Inspección de lotes de telemetría rechazados, diagnóstico sanitizado y decisiones operativas.
- **Administración:** Usuarios, roles RBAC (sistema y personalizados) y registros de auditoría inmutables.

## Comandos de Desarrollo

```bash
# Instalar dependencias
npm install

# Iniciar servidor de desarrollo con proxy a FastAPI (puerto 5173 -> 8000)
npm run dev

# Ejecutar verificación de tipos TypeScript
npm run typecheck

# Ejecutar suite de pruebas unitarias y componentes
npm run test

# Compilar paquete optimizado para producción
npm run build
```
