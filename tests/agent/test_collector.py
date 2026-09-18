from __future__ import annotations

from agent.nexus_agent.collector import CoreCollector


class Probe:
    def cpu_percent(self):
        return 12.5

    def memory(self):
        return {"total_bytes": 100, "available_bytes": 25, "used_percent": 75.0}

    def disks(self):
        return [{"mount": "/", "free_bytes": 50}]

    def networks(self):
        return [{"addresses": ["127.0.0.1"]}]

    def processes(self):
        return [{"name": "safe-process", "pid": 10}]

    def services(self):
        return [{"name": "safe-service", "state": "RUNNING"}]

    def smart(self):
        return [{"device": "disk0", "health": "PASSED"}]


def test_core_collector_uses_injected_platform_probe() -> None:
    collected = CoreCollector(Probe(), clock=lambda: 1234.0).collect()

    assert collected["recorded_at"] == 1234
    assert collected["cpu"] == {"used_percent": 12.5}
    assert collected["memory"]["used_percent"] == 75.0
    assert collected["processes"] == [{"name": "safe-process", "pid": 10}]
    assert collected["services"] == [{"name": "safe-service", "state": "RUNNING"}]
    assert collected["smart"] == [{"device": "disk0", "health": "PASSED"}]
