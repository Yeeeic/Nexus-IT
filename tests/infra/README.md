# Pruebas de Infraestructura y Rendimiento (NEXUS IT)

Este directorio contiene las pruebas de integración con base de datos real, aislamiento multiempresa PostgreSQL RLS, concurrencia masiva y scripts de prueba de carga con k6.

---

## 1. Pruebas de Concurrencia y RLS en Base de Datos

Las pruebas en `test_multitenant_rls.py` y `test_load_and_recovery.py` validan:
- Aislamiento estricto de filas por tenant (`app.current_organization_id`).
- Inserción masiva concurrente de telemetría sin condiciones de carrera.
- Recuperación de lotes fallidos a la cola Dead Letter Queue (DLQ).
- Diagnósticos sanitizados sin exposición de secretos.

### Ejecución de Pruebas con PostgreSQL Real:

```powershell
$env:NEXUS_RUN_DB_TESTS="1"
.\.venv\Scripts\python.exe -m pytest tests/infra/ -v
```

---

## 2. Pruebas de Carga con k6 (Incremento 14)

El script `k6_telemetry_load_test.js` evalúa los presupuestos de rendimiento del Incremento 14 del Roadmap:
- **Carga continua:** 50 - 200 agentes enviando lotes periódicos de métricas.
- **Ráfagas:** Transmisión simultánea de hasta 20 lotes/segundo.
- **Presupuesto de Latencia:** $P_{99} \le 150\text{ ms}$ en la ruta `/api/v1/devices/{device_id}/metrics/batches`.
- **Tolerancia a Fallos:** Tasa de error $< 1\%$.

### Cómo Ejecutar la Prueba k6:

```bash
# 1. Asegurarse de que el backend esté arriba
curl http://127.0.0.1:8000/health

# 2. Usar un dispositivo y token reales de prueba; un 401 invalida la prueba
NEXUS_TEST_DEVICE_ID=<uuid> \
NEXUS_AGENT_TOKEN=<token_id.token_secret> \
k6 run tests/infra/k6_telemetry_load_test.js
```
