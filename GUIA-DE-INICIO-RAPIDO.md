# Guía de Inicio Rápido: NEXUS IT

Esta guía te explica de forma sencilla qué debes abrir, prender, configurar y ejecutar para poner en marcha la plataforma **NEXUS IT** en tu computadora.

---

## 1. ¿Qué debes prender / abrir en tu computadora?

1. **Docker Desktop:**
   - Abre la aplicación **Docker Desktop** en Windows y espera unos segundos hasta que el icono esté en verde (*Engine Running*).
   - *(Docker se encarga de PostgreSQL con aislamiento RLS y Redis de forma automática y aislada)*.

---

## 2. ¿Qué configuración debes revisar?

El archivo `.env` en la raíz del proyecto ya contiene todas las variables de seguridad necesarias para desarrollo local:
- Puerto de la API: `8000`
- Base de datos: `nexus_it`
- Orígenes permitidos: `http://localhost:5173` (Frontend Vite)
- Claves criptográficas: Ed25519 para acciones remotas y Argon2id/Pepper para tokens.

---

## 3. Opciones de Ejecución

### Opción A: Modo Contenedores Todo en Uno (Recomendado para Producción/Staging)

Una vez que Docker Desktop esté encendido, abre PowerShell en la raíz del proyecto y ejecuta:

```powershell
# 1. Iniciar servicios de datos (PostgreSQL y Redis)
docker compose --env-file .env -f infra/compose.yaml up -d postgres redis

# 2. Aplicar migraciones iniciales de la base de datos
docker compose --env-file .env -f infra/compose.yaml --profile tools run --rm migrate

# 3. Aprovisionar usuario seguro de runtime
docker compose --env-file .env -f infra/compose.yaml --profile tools run --rm provision-runtime

# 4. Levantar Backend y Frontend (NGINX)
docker compose --env-file .env -f infra/compose.yaml up -d backend frontend
```

- **Frontend en el navegador:** `http://localhost:8080`
- **Backend API Docs:** `http://localhost:8000/docs`

---

### Opción B: Modo Desarrollo Rápido (Local)

El servidor de Frontend **ya se encuentra encendido y corriendo** en:
👉 **[http://localhost:5173/](http://localhost:5173/)**

Para iniciar el Backend en desarrollo local:
```powershell
# Activar entorno virtual de Python
.\.venv\Scripts\Activate.ps1

# Iniciar servidor FastAPI con recarga automática
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
```

---

## 4. ¿Cómo conectar un Agente de Monitoreo?

Para monitorear tu propia computadora o un servidor Windows/Linux:

1. Ve a la consola web (`http://localhost:5173/` o `http://localhost:8080`).
2. En la pestaña **Dispositivos**, haz clic en **"Registrar Dispositivo"** e ingresa el nombre de tu equipo (ej. `mi-laptop-dev`).
3. Haz clic en **"Token de Agente"** para copiar el token criptográfico generado.
4. En tu terminal ejecuta el agente en segundo plano:
   ```powershell
   python -m agent.nexus_agent.main --server-url http://127.0.0.1:8000 --token <TU_TOKEN_AQUI>
   ```
5. ¡Listo! Verás inmediatamente las métricas de CPU, RAM, disco e inventario de software reflejadas en tiempo real en la pantalla.
