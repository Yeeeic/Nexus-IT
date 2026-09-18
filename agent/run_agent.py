"""Executable NEXUS IT telemetry, inventory, and remote action agent.

Device enrollment happens in authenticated web console. This process accepts
only a previously issued device identity and token; it never handles human
administrator credentials. Never enables free shell or arbitrary command execution.
"""

from __future__ import annotations

import argparse
import base64
import ipaddress
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable, Mapping, Sequence
from urllib.parse import urlsplit
from uuid import UUID

from agent.nexus_agent.actions import (
    ACTION_CATALOG,
    ActionHandler,
    AgentActionOrder,
    SQLiteActionStore,
)
from agent.nexus_agent.collector import (
    CoreCollector,
    StandardSystemProbe,
    SystemProbe,
)
from agent.nexus_agent.dispatcher import BatchDispatcher, HttpResult
from agent.nexus_agent.permissions import harden_file
from agent.nexus_agent.protection import WindowsDpapiProtector
from agent.nexus_agent.storage import LocalQueue, QueueCapacityExceeded


def default_state_directory() -> Path:
    configured = os.getenv("NEXUS_AGENT_STATE_DIR")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        base = os.getenv("PROGRAMDATA")
        if base:
            return Path(base) / "NexusIT" / "Agent"
    return Path.home() / ".local" / "state" / "nexus-it-agent"


def _canonical_decimal(value: Decimal) -> str:
    rendered = format(value.normalize(), "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return "0" if rendered in {"-0", ""} else rendered


def _windows_cpu_times() -> tuple[int, int, int] | None:
    if platform.system() != "Windows":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        idle = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(  # type: ignore[attr-defined]
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
        ):
            return None

        def value(file_time: object) -> int:
            return (int(file_time.dwHighDateTime) << 32) | int(  # type: ignore[attr-defined]
                file_time.dwLowDateTime  # type: ignore[attr-defined]
            )

        return value(idle), value(kernel), value(user)
    except (AttributeError, OSError):
        return None


def _cpu_percent_between(
    previous: tuple[int, int, int], current: tuple[int, int, int]
) -> float | None:
    idle_delta = current[0] - previous[0]
    total_delta = (current[1] - previous[1]) + (current[2] - previous[2])
    if idle_delta < 0 or total_delta <= 0:
        return None
    return min(max((1.0 - idle_delta / total_delta) * 100.0, 0.0), 100.0)


def _memory_percent() -> float | None:
    if platform.system() == "Windows":
        try:
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("length", ctypes.c_ulong),
                    ("memory_load", ctypes.c_ulong),
                    ("total_physical", ctypes.c_ulonglong),
                    ("available_physical", ctypes.c_ulonglong),
                    ("total_page_file", ctypes.c_ulonglong),
                    ("available_page_file", ctypes.c_ulonglong),
                    ("total_virtual", ctypes.c_ulonglong),
                    ("available_virtual", ctypes.c_ulonglong),
                    ("available_extended_virtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatus()
            status.length = ctypes.sizeof(MemoryStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(  # type: ignore[attr-defined]
                ctypes.byref(status)
            ):
                return float(status.memory_load)
        except (AttributeError, OSError):
            return None
    if hasattr(os, "sysconf"):
        try:
            page_size = int(os.sysconf("SC_PAGE_SIZE"))
            total = page_size * int(os.sysconf("SC_PHYS_PAGES"))
            available = page_size * int(os.sysconf("SC_AVPHYS_PAGES"))
            return (total - available) / total * 100.0 if total else 0.0
        except (OSError, ValueError):
            pass
    return None


def validate_server_url(value: str, *, allow_insecure_http: bool) -> str:
    candidate = value.strip().rstrip("/")
    parsed = urlsplit(candidate)
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise ValueError("server URL must contain only scheme, host, and optional port")
    if parsed.scheme == "https":
        return candidate
    loopback = parsed.hostname.lower() in {"localhost", "127.0.0.1", "::1"}
    is_private_ip = False
    try:
        ip = ipaddress.ip_address(parsed.hostname)
        is_private_ip = ip.is_private or ip.is_loopback
    except ValueError:
        pass
    if parsed.scheme == "http" and allow_insecure_http and (loopback or is_private_ip):
        return candidate
    raise ValueError(
        "HTTPS is required; development HTTP needs --allow-insecure-http and a loopback or private network host"
    )


def load_config(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("agent configuration cannot be read") from error
    allowed = {"server_url", "device_id", "hostname", "public_keys", "inventory_interval"}
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError("agent configuration has unsupported fields")
    return value


def resolve_identity(
    config: Mapping[str, object],
    *,
    environment: Mapping[str, str] = os.environ,
) -> tuple[str, str]:
    device_id_raw = environment.get("NEXUS_AGENT_DEVICE_ID") or config.get("device_id")
    device_id = str(device_id_raw).strip() if device_id_raw else ""
    device_token = environment.get("NEXUS_AGENT_TOKEN", "").strip()
    if not device_id or not device_token:
        raise ValueError(
            "device identity missing; enroll in web console and configure "
            "NEXUS_AGENT_DEVICE_ID and NEXUS_AGENT_TOKEN"
        )
    try:
        identifier = UUID(device_id)
    except ValueError:
        raise ValueError("device ID must be a UUID") from None
    if identifier.version != 4:
        raise ValueError("device ID must be a UUIDv4")
    if len(device_token) > 512 or any(character.isspace() for character in device_token):
        raise ValueError("device token has invalid format")
    return str(identifier), device_token


def parse_public_keys(
    raw: object,
    *,
    environment: Mapping[str, str] = os.environ,
) -> dict[int, bytes]:
    result: dict[int, bytes] = {}
    if isinstance(raw, dict):
        for key, val in raw.items():
            try:
                version = int(key)
                if isinstance(val, str):
                    result[version] = base64.b64decode(val.strip())
                elif isinstance(val, bytes):
                    result[version] = val
            except Exception:
                continue

    env_keys = environment.get("NEXUS_AGENT_PUBLIC_KEYS")
    if env_keys:
        try:
            parsed = json.loads(env_keys)
            if isinstance(parsed, dict):
                for key, val in parsed.items():
                    try:
                        version = int(key)
                        if isinstance(val, str):
                            result[version] = base64.b64decode(val.strip())
                    except Exception:
                        continue
        except Exception:
            pass

    env_single_key = environment.get("NEXUS_ACTION_PUBLIC_KEY")
    if env_single_key and 1 not in result:
        try:
            result[1] = base64.b64decode(env_single_key.strip())
        except Exception:
            pass

    return result


def _read_json_response(raw: bytes) -> dict[str, object]:
    if not raw:
        return {}
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


class HttpMetricSender:
    def __init__(self, server_url: str, device_id: str, device_token: str) -> None:
        self._endpoint = f"{server_url}/api/v1/devices/{device_id}/metrics/batches"
        self._device_token = device_token

    def send(self, body: Mapping[str, object]) -> HttpResult:
        request = urllib.request.Request(
            self._endpoint,
            data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._device_token}",
                "Content-Type": "application/json",
                "User-Agent": f"NexusAgent/{platform.system()}-{platform.release()}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                parsed = _read_json_response(response.read())
                return HttpResult(
                    response.status,
                    remote_status=str(parsed.get("status", "")),
                )
        except urllib.error.HTTPError as error:
            parsed = _read_json_response(error.read())
            return HttpResult(
                error.code,
                error_code=str(parsed.get("code", "")),
                error_summary="server rejected telemetry batch",
            )
        except (OSError, TimeoutError):
            return HttpResult(0, error_summary="telemetry endpoint unavailable")


class HttpInventorySender:
    def __init__(self, server_url: str, device_id: str, device_token: str) -> None:
        self._endpoint = f"{server_url}/api/v1/devices/{device_id}/inventory"
        self._device_token = device_token

    def send(self, body: Mapping[str, object]) -> HttpResult:
        request = urllib.request.Request(
            self._endpoint,
            data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._device_token}",
                "Content-Type": "application/json",
                "User-Agent": f"NexusAgent/{platform.system()}-{platform.release()}",
            },
            method="PUT",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                parsed = _read_json_response(response.read())
                return HttpResult(response.status, remote_status=str(parsed.get("updated_at", "")))
        except urllib.error.HTTPError as error:
            parsed = _read_json_response(error.read())
            return HttpResult(
                error.code,
                error_code=str(parsed.get("code", "")),
                error_summary="server rejected inventory snapshot",
            )
        except (OSError, TimeoutError):
            return HttpResult(0, error_summary="inventory endpoint unavailable")


class HttpActionClient:
    def __init__(self, server_url: str, device_id: str, device_token: str) -> None:
        self._server_url = server_url
        self._device_id = device_id
        self._device_token = device_token

    def poll_actions(self) -> list[dict[str, object]]:
        endpoint = f"{self._server_url}/api/v1/devices/{self._device_id}/actions?limit=10"
        request = urllib.request.Request(
            endpoint,
            headers={
                "Authorization": f"Bearer {self._device_token}",
                "User-Agent": f"NexusAgent/{platform.system()}-{platform.release()}",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                parsed = _read_json_response(response.read())
                items = parsed.get("items")
                return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
        except Exception:
            return []

    def acknowledge_action(self, action_id: str) -> bool:
        endpoint = f"{self._server_url}/api/v1/devices/{self._device_id}/actions/{action_id}/ack"
        request = urllib.request.Request(
            endpoint,
            data=b"{}",
            headers={
                "Authorization": f"Bearer {self._device_token}",
                "Content-Type": "application/json",
                "User-Agent": f"NexusAgent/{platform.system()}-{platform.release()}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status in (200, 204)
        except Exception:
            return False

    def report_result(
        self,
        action_id: str,
        *,
        status: str,
        exit_code: int | None,
        output_summary: str,
    ) -> bool:
        endpoint = f"{self._server_url}/api/v1/devices/{self._device_id}/actions/{action_id}/result"
        payload = {
            "status": status,
            "exit_code": exit_code,
            "output_summary": output_summary[:2000],
        }
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._device_token}",
                "Content-Type": "application/json",
                "User-Agent": f"NexusAgent/{platform.system()}-{platform.release()}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status in (200, 204)
        except Exception:
            return False


def make_action_handlers(probe: SystemProbe | None = None) -> dict[str, ActionHandler]:
    active_probe = probe or StandardSystemProbe()

    def handle_restart_service(parameters: dict[str, object]) -> tuple[int, str]:
        service_name = str(parameters.get("service_name", "")).strip()
        if not service_name or any(c in service_name for c in ";|&$`\r\n"):
            return 1, "Invalid service name"
        if platform.system() == "Windows":
            res = subprocess.run(
                ["net", "stop", service_name],
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )
            res2 = subprocess.run(
                ["net", "start", service_name],
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )
            return (0 if res2.returncode == 0 else res2.returncode), (res2.stdout or res2.stderr).strip()[:500]
        res = subprocess.run(
            ["systemctl", "restart", service_name],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        return res.returncode, (res.stdout or res.stderr).strip()[:500]

    def handle_flush_dns(_parameters: dict[str, object]) -> tuple[int, str]:
        if platform.system() == "Windows":
            res = subprocess.run(
                ["ipconfig", "/flushdns"],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            return res.returncode, (res.stdout or res.stderr).strip()[:500]
        res = subprocess.run(
            ["resolvectl", "flush-caches"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        return res.returncode, (res.stdout or res.stderr).strip()[:500]

    def handle_collect_extended_diagnostics(_parameters: dict[str, object]) -> tuple[int, str]:
        collector = CoreCollector(active_probe)
        data = collector.collect()
        return 0, json.dumps(data, separators=(",", ":"))[:1000]

    def handle_reboot_system(parameters: dict[str, object]) -> tuple[int, str]:
        delay_raw = parameters.get("delay_seconds", 30)
        delay = max(0, min(int(delay_raw) if isinstance(delay_raw, int) else 30, 3600))
        if platform.system() == "Windows":
            res = subprocess.run(
                ["shutdown", "/r", "/t", str(delay)],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            return res.returncode, f"System reboot scheduled in {delay}s"
        mins = max(1, delay // 60)
        res = subprocess.run(
            ["shutdown", "-r", f"+{mins}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        return res.returncode, f"System reboot scheduled in {mins}m"

    return {
        "restart_service": handle_restart_service,
        "flush_dns": handle_flush_dns,
        "collect_extended_diagnostics": handle_collect_extended_diagnostics,
        "reboot_system": handle_reboot_system,
    }


def collect_system_inventory(probe: SystemProbe | None = None) -> dict[str, object]:
    probe = probe or StandardSystemProbe()
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    memory_info = probe.memory()
    total_mem = memory_info.get("total_bytes")
    if total_mem is None or total_mem <= 0:
        total_mem = 1024 * 1024 * 1024

    cpu_model = platform.processor() or platform.machine() or "Unknown CPU"
    cpu_count = os.cpu_count() or 1

    hardware = {
        "cpu_model": cpu_model[:200],
        "physical_cores": max(1, cpu_count // 2) if cpu_count > 1 else 1,
        "logical_processors": max(1, cpu_count),
        "memory_bytes": int(total_mem),
    }

    services_list = []
    for svc in probe.services():
        services_list.append(
            {
                "name": str(svc.get("name", "unknown"))[:255],
                "display_name": str(svc.get("display_name", ""))[:255] if svc.get("display_name") else None,
                "status": "RUNNING" if svc.get("status") == "RUNNING" else "STOPPED",
                "start_type": "AUTO" if svc.get("start_type") == "AUTO" else "MANUAL",
            }
        )

    return {
        "hardware": hardware,
        "software_packages": [],
        "patches": [],
        "services": services_list[:1000],
        "collected_at": now,
    }


class NexusAgent:
    def __init__(
        self,
        server_url: str,
        device_id: str,
        device_token: str,
        queue: LocalQueue,
        *,
        action_store: SQLiteActionStore | None = None,
        public_keys: Mapping[int, bytes] | None = None,
        probe: SystemProbe | None = None,
        hostname: str | None = None,
        action_handlers: Mapping[str, ActionHandler] | None = None,
    ) -> None:
        self.server_url = server_url
        self.device_id = device_id
        self.hostname = hostname or socket.gethostname()
        self.queue = queue
        self.public_keys = dict(public_keys or {})
        self.action_store = action_store
        self.probe = probe or StandardSystemProbe()
        self.action_handlers = action_handlers or make_action_handlers(self.probe)
        self._previous_windows_cpu_times = _windows_cpu_times()
        self.dispatcher = BatchDispatcher(
            queue,
            HttpMetricSender(server_url, device_id, device_token),
        )
        self.inventory_sender = HttpInventorySender(server_url, device_id, device_token)
        self.action_client = HttpActionClient(server_url, device_id, device_token)

    def sample_metrics(self) -> list[dict[str, object]]:
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        cpu_percent: float | None = None
        if platform.system() == "Windows":
            current_cpu_times = _windows_cpu_times()
            if self._previous_windows_cpu_times is not None and current_cpu_times is not None:
                cpu_percent = _cpu_percent_between(
                    self._previous_windows_cpu_times, current_cpu_times
                )
            self._previous_windows_cpu_times = current_cpu_times
        else:
            try:
                load = os.getloadavg()[0]
                cpu_percent = min(
                    max(load / (os.cpu_count() or 1) * 100.0, 0.0), 100.0
                )
            except (AttributeError, OSError):
                pass

        disk_percent: float | None = None
        try:
            root = "C:\\" if platform.system() == "Windows" else "/"
            usage = shutil.disk_usage(root)
            disk_percent = usage.used / usage.total * 100.0 if usage.total else None
        except OSError:
            pass

        labels = {
            "host": self.hostname.lower()[:32],
            "os": platform.system().lower()[:16],
        }
        measurements = (
            ("system.cpu_percent", cpu_percent),
            ("system.memory_used_percent", _memory_percent()),
            ("system.disk_used_percent", disk_percent),
        )
        return [
            {
                "labels": dict(sorted(labels.items())),
                "metric_name": name,
                "metric_value": _canonical_decimal(Decimal(str(round(value, 2)))),
                "recorded_at": now,
            }
            for name, value in measurements
            if value is not None
        ]

    def collect_and_enqueue(self) -> str:
        return self.queue.enqueue(self.sample_metrics())

    def collect_and_send_inventory(self) -> HttpResult:
        payload = collect_system_inventory(self.probe)
        return self.inventory_sender.send(payload)

    def poll_and_execute_actions(self) -> int:
        if not self.public_keys or self.action_store is None:
            return 0
        actions = self.action_client.poll_actions()
        executed_count = 0
        now = datetime.now(timezone.utc)
        for action_data in actions:
            try:
                action_id_str = str(action_data.get("id"))
                order = AgentActionOrder(
                    action_execution_id=UUID(action_id_str),
                    organization_id=UUID(str(action_data.get("organization_id"))),
                    device_id=UUID(str(self.device_id)),
                    nonce=UUID(str(action_data.get("nonce"))),
                    action_name=str(action_data.get("action_name")),
                    action_version=int(action_data.get("action_version", 1)),
                    key_version=int(action_data.get("key_version", 1)),
                    issued_at=str(action_data.get("issued_at")),
                    expires_at=str(action_data.get("expires_at")),
                    order_digest=str(action_data.get("order_digest")),
                    signature=str(action_data.get("signature")),
                    parameters_canonical=str(action_data.get("parameters_canonical")),
                )
                accepted = self.action_store.verify_and_accept(
                    order,
                    public_keys=self.public_keys,
                    now=now,
                )
                if not accepted:
                    continue
                self.action_client.acknowledge_action(action_id_str)
                executed = self.action_store.execute_once(
                    order.action_execution_id,
                    self.action_handlers,
                )
                if executed:
                    status = self.action_store.status(order.action_execution_id)
                    with self.action_store._connect() as conn:
                        row = conn.execute(
                            "SELECT exit_code, output_summary FROM action_states WHERE action_execution_id = ?",
                            (action_id_str,),
                        ).fetchone()
                        exit_code = row["exit_code"] if row else None
                        summary = row["output_summary"] if row else ""
                    self.action_client.report_result(
                        action_id_str,
                        status=status or "SUCCEEDED",
                        exit_code=exit_code,
                        output_summary=summary or "",
                    )
                    executed_count += 1
            except Exception as error:
                print(f"Action execution error: {error}", file=sys.stderr)
        return executed_count


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NEXUS IT telemetry agent")
    parser.add_argument("--server", help="NEXUS IT HTTPS origin")
    parser.add_argument("--device-id", help="non-secret device UUID")
    parser.add_argument("--hostname", help="host label sent with metrics")
    parser.add_argument("--interval", type=int, default=30, help="collection interval, seconds")
    parser.add_argument("--inventory-interval", type=int, default=300, help="inventory upload interval, seconds")
    parser.add_argument("--config", type=Path, help="runtime configuration path")
    parser.add_argument(
        "--allow-insecure-http",
        action="store_true",
        help="allow HTTP only for loopback development",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.interval < 5:
        raise SystemExit("collection interval must be at least 5 seconds")

    state_directory = default_state_directory()
    config_path = args.config or Path(
        os.getenv("NEXUS_AGENT_CONFIG", state_directory / "agent_config.json")
    )
    try:
        config = load_config(config_path)
        merged = dict(config)
        if args.device_id:
            merged["device_id"] = args.device_id
        server_url = validate_server_url(
            args.server
            or os.getenv("NEXUS_AGENT_SERVER_URL", "")
            or str(merged.get("server_url", "")),
            allow_insecure_http=args.allow_insecure_http,
        )
        device_id, device_token = resolve_identity(merged)
        public_keys = parse_public_keys(merged.get("public_keys"))
    except ValueError as error:
        raise SystemExit(str(error)) from None

    if config_path.exists():
        harden_file(config_path)
    protector = WindowsDpapiProtector() if os.name == "nt" else None
    queue = LocalQueue(state_directory / "agent.db", protector=protector)
    action_store = SQLiteActionStore(state_directory / "actions.sqlite3")
    action_store.reconcile_after_restart(now_epoch=int(time.time()))

    agent = NexusAgent(
        server_url,
        device_id,
        device_token,
        queue,
        action_store=action_store,
        public_keys=public_keys,
        hostname=args.hostname or (str(merged.get("hostname")) if merged.get("hostname") else None),
    )

    print(f"NEXUS IT agent started for device {device_id}; endpoint {server_url}")
    last_inventory_time = 0.0
    inventory_interval = max(30, args.inventory_interval or int(merged.get("inventory_interval", 300)))

    try:
        while True:
            # 1. Telemetry
            try:
                agent.collect_and_enqueue()
            except QueueCapacityExceeded:
                print("telemetry queue full; protected records preserved", file=sys.stderr)
            outcome = agent.dispatcher.dispatch_once().outcome
            print(f"telemetry dispatch: {outcome}")

            # 2. Inventory
            now_time = time.time()
            if now_time - last_inventory_time >= inventory_interval:
                inv_res = agent.collect_and_send_inventory()
                outcome = "ACCEPTED" if 200 <= inv_res.status_code < 300 else f"FAILED ({inv_res.status_code})"
                print(f"inventory dispatch: {outcome}")
                last_inventory_time = now_time

            # 3. Actions
            executed = agent.poll_and_execute_actions()
            if executed > 0:
                print(f"remote actions executed: {executed}")

            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("NEXUS IT agent stopped")


if __name__ == "__main__":
    main()
