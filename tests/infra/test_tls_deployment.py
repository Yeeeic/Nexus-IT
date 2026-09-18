"""Guard against exposing the development HTTP ports alongside TLS."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_tls_override_replaces_public_http_bindings():
    config = (ROOT / "infra/compose.tls.yaml").read_text(encoding="utf-8")
    assert 'ports: !override\n      - "127.0.0.1:' in config
    assert "ports: !override []" in config
    assert "NEXUS_TLS_CERT_FILE:?" in config
    assert "NEXUS_TLS_KEY_FILE:?" in config
    assert config.count("create_host_path: false") == 2
    assert "nginx:1.27-alpine@sha256:" in config


def test_edge_enforces_tls_and_preserves_authenticated_websockets():
    config = (ROOT / "infra/nginx/tls.conf").read_text(encoding="utf-8")
    assert "ssl_protocols TLSv1.3;" in config
    assert "return 301 https://$host$request_uri;" in config
    assert 'Strict-Transport-Security "max-age=31536000" always' in config
    assert "proxy_pass http://backend:8000;" in config
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in config
    assert "proxy_set_header Upgrade $http_upgrade;" in config
    assert "proxy_set_header Connection $connection_upgrade;" in config
    assert "client_max_body_size 11m;" in config
