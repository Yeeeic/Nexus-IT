#!/usr/bin/env bash
set -euo pipefail

echo "========================================"
echo "   NEXUS IT - Instalador Linux/Ubuntu   "
echo "========================================"

SERVER_URL="${1:-}"
DEVICE_ID="${2:-}"
TOKEN="${3:-}"
PUBLIC_KEYS_JSON="${4:-}"
ARTIFACT_BASE_URL="${5:-$SERVER_URL}"
ALLOW_INSECURE_HTTP="${6:-false}"

if [ -z "$SERVER_URL" ] || [ -z "$DEVICE_ID" ] || [ -z "$TOKEN" ] || [ -z "$PUBLIC_KEYS_JSON" ]; then
    echo "Uso: sudo bash install-agent.sh <SERVER_URL> <DEVICE_ID> <TOKEN> <PUBLIC_KEYS_JSON> [ARTIFACT_BASE_URL] [ALLOW_INSECURE_HTTP]"
    exit 1
fi

if [[ "$SERVER_URL" == http://* ]] && [ "$ALLOW_INSECURE_HTTP" != "true" ]; then
    echo "HTTP requiere ALLOW_INSECURE_HTTP=true y solo debe usarse en desarrollo controlado."
    exit 1
fi

INSTALL_DIR="/opt/nexus-it-agent"
mkdir -p "$INSTALL_DIR"

echo "[1/3] Verificando dependencias del sistema..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-cryptography curl unzip > /dev/null

export NEXUS_INSTALL_PUBLIC_KEYS="$PUBLIC_KEYS_JSON"
python3 - <<'PY'
import base64
import json
import os

keys = json.loads(os.environ["NEXUS_INSTALL_PUBLIC_KEYS"])
if not isinstance(keys, dict) or not keys:
    raise SystemExit("PUBLIC_KEYS_JSON debe contener al menos una clave")
for version, encoded in keys.items():
    if not str(version).isdigit() or not isinstance(encoded, str):
        raise SystemExit("Mapa de claves Ed25519 inválido")
    if len(base64.b64decode(encoded, validate=True)) != 32:
        raise SystemExit("Clave pública Ed25519 inválida")
PY

echo "[2/3] Descargando codigo del agente..."
ARTIFACT_BASE_URL="${ARTIFACT_BASE_URL%/}"
curl --fail --show-error --silent --location -o "$INSTALL_DIR/agent.zip" "$ARTIFACT_BASE_URL/agent-linux.zip"
unzip -qo "$INSTALL_DIR/agent.zip" -d "$INSTALL_DIR"

echo "[3/3] Configurando servicio systemd..."
ENV_FILE="/etc/nexus-it-agent.env"
escape_systemd_value() {
    printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}
{
    printf 'NEXUS_AGENT_SERVER_URL="%s"\n' "$(escape_systemd_value "$SERVER_URL")"
    printf 'NEXUS_AGENT_DEVICE_ID="%s"\n' "$(escape_systemd_value "$DEVICE_ID")"
    printf 'NEXUS_AGENT_TOKEN="%s"\n' "$(escape_systemd_value "$TOKEN")"
    printf 'NEXUS_AGENT_PUBLIC_KEYS="%s"\n' "$(escape_systemd_value "$PUBLIC_KEYS_JSON")"
} > "$ENV_FILE"
chmod 600 "$ENV_FILE"

AGENT_FLAGS=""
if [ "$ALLOW_INSECURE_HTTP" = "true" ]; then
    AGENT_FLAGS="--allow-insecure-http"
fi

cat << EOF > /etc/systemd/system/nexus-agent.service
[Unit]
Description=NEXUS IT Telemetry & Monitoring Agent
After=network.target

[Service]
Type=simple
EnvironmentFile=$ENV_FILE
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/python3 -m agent.run_agent $AGENT_FLAGS --interval 15
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now nexus-agent.service

echo "========================================"
echo "  Agente NEXUS IT activo en systemd!"
echo "========================================"
