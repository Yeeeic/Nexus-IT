# Agent

Python monitoring core for Windows and Linux. It provides:

- dependency-free baseline collection with injectable privileged collectors;
- a bounded SQLite queue using WAL and `synchronous=FULL`;
- FIFO eviction of old periodic telemetry while preserving critical records;
- corruption detection with forensic database isolation;
- terminal encrypted quarantine for HTTP 422 and oversized single samples;
- symmetric HTTP 413 splitting with at most three levels;
- exponential retry for network, rate-limit, and server failures.

Quarantine encryption fails closed unless an OS-backed `PayloadProtector` is
configured. Windows includes a machine-scoped DPAPI implementation. Linux
deployments must inject a protector backed by a machine key kept outside the
database and source code. Remote arbitrary command execution remains prohibited.

## Ejecución segura

El dispositivo y su token se crean desde la consola autenticada. El agente no
recibe credenciales humanas ni se autoenrola.

```powershell
$env:NEXUS_AGENT_SERVER_URL="https://nexus.example.com"
$env:NEXUS_AGENT_DEVICE_ID="<uuid-v4>"
$env:NEXUS_AGENT_TOKEN="<token-entregado-una-sola-vez>"
python -m agent.run_agent
```

`agent_config.example.json` documenta campos no secretos. El archivo runtime
`agent_config.json` está ignorado por Git. HTTPS es obligatorio; HTTP solo está
permitido en loopback con `--allow-insecure-http` para desarrollo explícito.

Telemetría usa cola durable SQLite. El runner (`agent.run_agent`) recolecta periódicamente inventario de hardware y servicios (`PUT /api/v1/devices/{device_id}/inventory`) y sondea acciones remotas firmadas con Ed25519 (`GET /api/v1/devices/{device_id}/actions`), confirmando recepción (`ack`) y ejecutando exclusivamente los comandos del catálogo cerrado (`restart_service`, `flush_dns`, `collect_extended_diagnostics`, `reboot_system`) sin shell libre.
