"""Small, dependency-free collectors with injectable platform providers."""

from __future__ import annotations

import os
import platform
import shutil
import socket
import time
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .compat import dataclass, Protocol


class SystemProbe(Protocol):
    def cpu_percent(self) -> float | None: ...

    def memory(self) -> Mapping[str, int | float | None]: ...

    def disks(self) -> Sequence[Mapping[str, object]]: ...

    def networks(self) -> Sequence[Mapping[str, object]]: ...

    def processes(self) -> Sequence[Mapping[str, object]]: ...

    def services(self) -> Sequence[Mapping[str, object]]: ...

    def smart(self) -> Sequence[Mapping[str, object]]: ...


class StandardSystemProbe:
    """Portable baseline. Privileged process/service/SMART probes are injected."""

    def __init__(
        self,
        *,
        roots: Sequence[Path] | None = None,
        process_provider: Callable[[], Sequence[Mapping[str, object]]] = tuple,
        service_provider: Callable[[], Sequence[Mapping[str, object]]] = tuple,
        smart_provider: Callable[[], Sequence[Mapping[str, object]]] = tuple,
    ) -> None:
        self._roots = tuple(roots or ([Path.home().anchor] if Path.home().anchor else [Path("/")]))
        self._process_provider = process_provider
        self._service_provider = service_provider
        self._smart_provider = smart_provider

    def cpu_percent(self) -> float | None:
        try:
            load = os.getloadavg()[0]
        except (AttributeError, OSError):
            return None
        count = os.cpu_count() or 1
        return round(min(max(load / count * 100.0, 0.0), 100.0), 2)

    def memory(self) -> Mapping[str, int | float | None]:
        if hasattr(os, "sysconf"):
            try:
                page = int(os.sysconf("SC_PAGE_SIZE"))
                total = page * int(os.sysconf("SC_PHYS_PAGES"))
                available = page * int(os.sysconf("SC_AVPHYS_PAGES"))
                used_percent = round((total - available) / total * 100.0, 2) if total else None
                return {"total_bytes": total, "available_bytes": available, "used_percent": used_percent}
            except (OSError, ValueError):
                pass
        return {"total_bytes": None, "available_bytes": None, "used_percent": None}

    def disks(self) -> Sequence[Mapping[str, object]]:
        result: list[Mapping[str, object]] = []
        for root in self._roots:
            try:
                usage = shutil.disk_usage(root)
            except OSError:
                continue
            result.append(
                {
                    "mount": str(root),
                    "total_bytes": usage.total,
                    "used_bytes": usage.used,
                    "free_bytes": usage.free,
                }
            )
        return result

    def networks(self) -> Sequence[Mapping[str, object]]:
        try:
            addresses = sorted({item[4][0] for item in socket.getaddrinfo(socket.gethostname(), None)})
        except OSError:
            addresses = []
        return [{"host": socket.gethostname(), "addresses": addresses}]

    def processes(self) -> Sequence[Mapping[str, object]]:
        return self._process_provider()

    def services(self) -> Sequence[Mapping[str, object]]:
        return self._service_provider()

    def smart(self) -> Sequence[Mapping[str, object]]:
        return self._smart_provider()


@dataclass(frozen=True, slots=True)
class CoreCollector:
    probe: SystemProbe
    clock: Callable[[], float] = time.time

    def collect(self) -> dict[str, object]:
        return {
            "recorded_at": int(self.clock()),
            "host": {"hostname": socket.gethostname(), "os": platform.system(), "release": platform.release()},
            "cpu": {"used_percent": self.probe.cpu_percent()},
            "memory": dict(self.probe.memory()),
            "disks": [dict(item) for item in self.probe.disks()],
            "networks": [dict(item) for item in self.probe.networks()],
            "processes": [dict(item) for item in self.probe.processes()],
            "services": [dict(item) for item in self.probe.services()],
            "smart": [dict(item) for item in self.probe.smart()],
        }
