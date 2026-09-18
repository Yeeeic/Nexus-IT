import { describe, it, expect, vi, beforeEach } from "vitest";
import { devicesApi } from "@/api/devices";
import { metricsApi } from "@/api/metrics";
import { ticketsApi } from "@/api/tickets";
import { actionsApi } from "@/api/actions";
import { adminApi } from "@/api/admin";

describe("API Modules Contract Integration", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("devicesApi.list queries /devices and unwraps DeviceListResponse", async () => {
    const mockList = {
      items: [
        {
          id: "dev-1",
          hostname: "srv-01",
          display_name: "Web 01",
          is_active: true,
          last_seen_at: "2026-08-25T10:00:00Z",
          created_at: "2026-08-20T10:00:00Z",
          updated_at: "2026-08-25T10:00:00Z",
        },
      ],
      next_cursor: null,
    };

    vi.spyOn(global, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(mockList), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    const result = await devicesApi.list({ limit: 10 });
    expect(result.items).toHaveLength(1);
    expect(result.items[0]?.hostname).toBe("srv-01");
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/v1/devices?limit=10",
      expect.objectContaining({ method: "GET" })
    );
  });

  it("devicesApi.update sends PATCH /devices/{id}", async () => {
    const mockUpdated = {
      id: "dev-1",
      hostname: "srv-01",
      display_name: "Production DB",
      is_active: true,
      last_seen_at: null,
      created_at: "2026-08-20T10:00:00Z",
      updated_at: "2026-08-25T10:00:00Z",
    };

    vi.spyOn(global, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(mockUpdated), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    const result = await devicesApi.update("dev-1", { display_name: "Production DB" });
    expect(result.display_name).toBe("Production DB");
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/v1/devices/dev-1",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ display_name: "Production DB" }),
      })
    );
  });

  it("metricsApi.getTelemetry queries device-scoped telemetry", async () => {
    const mockTelemetry = {
      items: [
        {
          id: "tel-1",
          device_id: "dev-1",
          metric_name: "system.cpu.usage",
          metric_value: 45.2,
          recorded_at: "2026-08-25T12:00:00Z",
          labels: {},
        },
      ],
    };

    vi.spyOn(global, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(mockTelemetry), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    const result = await metricsApi.getTelemetry("dev-1", { metric_name: "system.cpu.usage", limit: 5 });
    expect(result.items).toHaveLength(1);
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/v1/devices/dev-1/metrics/telemetry?metric_name=system.cpu.usage&limit=5",
      expect.objectContaining({ method: "GET" })
    );
  });

  it("ticketsApi.transition sends PATCH /tickets/{id}/status", async () => {
    const mockTransition = {
      id: "tck-1",
      status: "IN_PROGRESS",
    };

    vi.spyOn(global, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(mockTransition), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    const result = await ticketsApi.transition("tck-1", {
      expected_status: "OPEN",
      status: "IN_PROGRESS",
    });

    expect(result.status).toBe("IN_PROGRESS");
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/v1/tickets/tck-1/status",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ expected_status: "OPEN", status: "IN_PROGRESS" }),
      })
    );
  });

  it("actionsApi.create sends POST /devices/{deviceId}/actions", async () => {
    const mockAction = {
      organization_id: "org-1",
      id: "act-1",
      device_id: "dev-1",
      action_name: "flush_dns",
      nonce: "nonce-1",
      key_version: 1,
      issued_at: "2026-08-25T12:00:00Z",
      expires_at: "2026-08-25T12:05:00Z",
      signature: "sig",
      parameters: {},
      status: "DISPATCHED",
    };

    vi.spyOn(global, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(mockAction), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    const result = await actionsApi.create("dev-1", {
      action_name: "flush_dns",
      parameters: {},
    });

    expect(result.action_name).toBe("flush_dns");
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/v1/devices/dev-1/actions",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ action_name: "flush_dns", parameters: {} }),
      })
    );
  });

  it("adminApi.listPermissions returns canonical permissions", async () => {
    const mockPerms = {
      items: [
        { code: "devices:read", name: "Leer dispositivos", description: "Ver inventario" },
        { code: "tickets:create", name: "Crear tickets", description: "Abrir tickets" },
      ],
    };

    vi.spyOn(global, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(mockPerms), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    const result = await adminApi.listPermissions();
    expect(result.items).toHaveLength(2);
    expect(result.items[0]?.code).toBe("devices:read");
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/v1/permissions",
      expect.objectContaining({ method: "GET" })
    );
  });
});
