#!/usr/bin/env bash
# Local disposable verification. No real certificate, environment or app state.
set -Eeuo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
scratch="$(mktemp -d /tmp/nexus-tls-test.XXXXXX)"
chmod 755 "$scratch"
name="nexus-tls-test-$(date +%s)-$$"
image=nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10
cleanup() {
    docker rm -f "$name" >/dev/null 2>&1 || true
    # Only the exact mktemp directory created above is removed.
    case "$scratch" in /tmp/nexus-tls-test.*) rm -r -- "$scratch";; esac
}
trap cleanup EXIT
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=localhost \
    -addext subjectAltName=DNS:localhost -keyout "$scratch/privatekey.pem" \
    -out "$scratch/fullchain.pem" >/dev/null 2>&1
chmod 644 "$scratch/privatekey.pem" "$scratch/fullchain.pem"
docker run --rm --network none --add-host backend:127.0.0.1 --add-host frontend:127.0.0.1 \
    -v "$root/infra/nginx/tls.conf:/etc/nginx/conf.d/default.conf:ro" \
    -v "$scratch:/run/nexus-tls:ro" "$image" nginx -t
docker run -d --name "$name" --add-host backend:127.0.0.1 --add-host frontend:127.0.0.1 \
    --read-only --cap-drop ALL --cap-add CHOWN --cap-add SETUID --cap-add SETGID \
    --security-opt no-new-privileges:true \
    --tmpfs /var/cache/nginx:uid=101,gid=101,mode=1777 --tmpfs /var/run:mode=1777 \
    -p 127.0.0.1:18443:8443 -p 127.0.0.1:18081:8080 \
    -v "$root/infra/nginx/tls.conf:/etc/nginx/conf.d/default.conf:ro" \
    -v "$scratch:/run/nexus-tls:ro" --entrypoint nginx "$image" -g 'daemon off;' >/dev/null
tls_port=18443
http_port=18081
sleep 1
for attempt in {1..20}; do
    if curl --silent --fail --cacert "$scratch/fullchain.pem" \
        "https://localhost:$tls_port/tls-health" -D "$scratch/headers" >/dev/null; then break; fi
    sleep 0.2
done
grep -qi 'strict-transport-security: max-age=31536000' "$scratch/headers"
curl --silent --fail --cacert "$scratch/fullchain.pem" --tlsv1.3 \
    "https://localhost:$tls_port/tls-health" >/dev/null
if curl --silent --cacert "$scratch/fullchain.pem" --tls-max 1.2 \
    "https://localhost:$tls_port/tls-health" >/dev/null 2>&1; then
    echo 'TLS 1.2 was unexpectedly accepted' >&2; exit 1
fi
curl --silent "http://localhost:$http_port/check" -D "$scratch/redirect" >/dev/null
grep -q '301 Moved Permanently' "$scratch/redirect"
grep -qi 'Location: https://localhost/check' "$scratch/redirect"
echo 'TLS_VERIFY_OK: nginx config, trusted TLS 1.3, TLS 1.2 rejection, HSTS, HTTP redirect'
