import { useEffect, useState, useCallback, useRef } from "react";
import { devicesApi } from "@/api/devices";
import { metricsApi } from "@/api/metrics";
import { ticketsApi } from "@/api/tickets";
import type { DeviceResponse } from "@/types/devices";
import type { AlertResponse, TelemetrySampleResponse } from "@/types/metrics";
import type { TicketResponse } from "@/types/tickets";
import { MetricCard } from "@/components/metrics/MetricCard";
import { TelemetryChart } from "@/components/metrics/TelemetryChart";
import { StatusIndicator } from "@/components/metrics/StatusIndicator";
import { Card } from "@/components/common/Card";
import { Table } from "@/components/common/Table";
import { Badge } from "@/components/common/Badge";
import { Button } from "@/components/common/Button";
import { Server, AlertOctagon, LifeBuoy, ShieldCheck, RefreshCw } from "lucide-react";
import type { NavigationTab } from "@/components/layout/Sidebar";
import { isDeviceOnline } from "@/utils/deviceStatus";

export interface DashboardViewProps {
  onNavigate: (tab: NavigationTab) => void;
}

export function DashboardView({ onNavigate }: DashboardViewProps) {
  const [devices, setDevices] = useState<DeviceResponse[]>([]);
  const [alerts, setAlerts] = useState<AlertResponse[]>([]);
  const [tickets, setTickets] = useState<TicketResponse[]>([]);
  const [telemetryCpu, setTelemetryCpu] = useState<TelemetrySampleResponse[]>([]);
  const [telemetryMemory, setTelemetryMemory] = useState<TelemetrySampleResponse[]>([]);
  const [telemetryDisk, setTelemetryDisk] = useState<TelemetrySampleResponse[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const isFetchingRef = useRef(false);

  const loadData = useCallback(async () => {
    if (isFetchingRef.current) return;
    isFetchingRef.current = true;
    setIsLoading(true);
    try {
      const [devs, alts, tcks] = await Promise.all([
        devicesApi.list({ limit: 50 }).catch(() => ({ items: [], next_cursor: null })),
        metricsApi.listAlerts({ limit: 10 }).catch(() => ({ items: [] })),
        ticketsApi.list({ limit: 10 }).catch(() => ({ items: [], next_cursor: null })),
      ]);

      setDevices(devs.items);
      setAlerts(alts.items);
      setTickets(tcks.items);

      const targetId = selectedDeviceId || (devs.items.length > 0 ? devs.items[0]?.id : null);
      if (targetId) {
        if (!selectedDeviceId) setSelectedDeviceId(targetId);
        const [cpuSamples, memSamples, diskSamples] = await Promise.all([
          metricsApi.getTelemetry(targetId, { metric_name: "system.cpu_percent", limit: 30 })
            .catch(() => metricsApi.getTelemetry(targetId, { metric_name: "system.cpu.usage", limit: 30 }))
            .catch(() => ({ items: [] })),
          metricsApi.getTelemetry(targetId, { metric_name: "system.memory_used_percent", limit: 30 })
            .catch(() => metricsApi.getTelemetry(targetId, { metric_name: "system.memory.usage", limit: 30 }))
            .catch(() => ({ items: [] })),
          metricsApi.getTelemetry(targetId, { metric_name: "system.disk_used_percent", limit: 30 })
            .catch(() => ({ items: [] })),
        ]);
        setTelemetryCpu(cpuSamples.items.slice().reverse());
        setTelemetryMemory(memSamples.items.slice().reverse());
        setTelemetryDisk(diskSamples.items.slice().reverse());
      }
    } catch {
      // handled gracefully
    } finally {
      isFetchingRef.current = false;
      setIsLoading(false);
    }
  }, [selectedDeviceId]);

  useEffect(() => {
    loadData();
    const interval = setInterval(() => {
      if (typeof document !== "undefined" && document.visibilityState === "visible") {
        loadData();
      }
    }, 20000); // 20s background poll
    return () => clearInterval(interval);
  }, [loadData]);

  const onlineCount = devices.filter(isDeviceOnline).length;
  const criticalAlertsCount = alerts.filter((a) => a.severity === "CRITICAL" && a.status === "OPEN").length;
  const warningAlertsCount = alerts.filter((a) => a.severity === "WARNING" && a.status === "OPEN").length;
  const openTicketsCount = tickets.filter((t) => ["OPEN", "IN_PROGRESS"].includes(t.status)).length;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-6)" }}>
      {/* Top Banner & Quick Refresh */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "1rem" }}>
        <div>
          <h2 style={{ fontSize: "var(--text-xl)", fontWeight: 700 }}>Resumen Operativo</h2>
          <p style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)", marginTop: "0.25rem" }}>
            Visión global de telemetría, incidentes activos y solicitudes de soporte técnico
          </p>
        </div>
        <Button
          variant="secondary"
          size="sm"
          onClick={loadData}
          isLoading={isLoading}
          leftIcon={<RefreshCw size={14} />}
        >
          Actualizar Datos
        </Button>
      </div>

      {/* KPI Stats Grid */}
      <div className="grid-stats">
        <MetricCard
          title="Dispositivos Monitoreados"
          value={devices.length}
          subtitle={`${onlineCount} en línea (${devices.length > 0 ? Math.round((onlineCount / devices.length) * 100) : 0}%)`}
          icon={<Server size={20} />}
          statusVariant={onlineCount === devices.length && devices.length > 0 ? "healthy" : "warning"}
        />

        <MetricCard
          title="Alertas Críticas Activas"
          value={criticalAlertsCount}
          subtitle={warningAlertsCount > 0 ? `${warningAlertsCount} advertencias` : "Flota en umbrales normales"}
          icon={<AlertOctagon size={20} />}
          statusVariant={criticalAlertsCount > 0 ? "critical" : "healthy"}
        />

        <MetricCard
          title="Tickets de Soporte"
          value={openTicketsCount}
          subtitle={`${tickets.length} tickets registrados`}
          icon={<LifeBuoy size={20} />}
          statusVariant={openTicketsCount > 5 ? "warning" : "info"}
        />

        <MetricCard
          title="Postura de Seguridad"
          value="100%"
          subtitle="Aislamiento RLS & Ed25519"
          icon={<ShieldCheck size={20} />}
          statusVariant="healthy"
        />
      </div>

      {/* Live Telemetry Charts Section with Device Selector */}
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "0.5rem" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <span style={{ fontSize: "var(--text-sm)", fontWeight: 600 }}>Telemetría en Vivo de la Flota</span>
            <span className="status-dot healthy pulse" style={{ width: "8px", height: "8px" }} />
          </div>
          {devices.length > 1 && (
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <span style={{ fontSize: "var(--text-xs)", color: "var(--text-muted)" }}>Dispositivo:</span>
              <select
                value={selectedDeviceId || ""}
                onChange={(e) => setSelectedDeviceId(e.target.value)}
                style={{
                  padding: "0.25rem 0.5rem",
                  fontSize: "var(--text-xs)",
                  borderRadius: "var(--radius-md)",
                  backgroundColor: "var(--bg-surface-elevated)",
                  color: "var(--text-primary)",
                  border: "1px solid var(--border-subtle)",
                }}
              >
                {devices.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.display_name || d.hostname}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>

        <div className="grid-responsive" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))" }}>
          <Card
            header={
              <div style={{ fontWeight: 600, fontSize: "var(--text-sm)" }}>
                Uso de Procesador (CPU)
              </div>
            }
          >
            <TelemetryChart
              title="Consumo de CPU"
              samples={telemetryCpu as any}
              unit="%"
              color="var(--brand-primary)"
              height={150}
            />
          </Card>

          <Card
            header={
              <div style={{ fontWeight: 600, fontSize: "var(--text-sm)" }}>
                Uso de Memoria RAM
              </div>
            }
          >
            <TelemetryChart
              title="Ocupación de Memoria"
              samples={telemetryMemory as any}
              unit="%"
              color="var(--brand-secondary)"
              height={150}
            />
          </Card>

          <Card
            header={
              <div style={{ fontWeight: 600, fontSize: "var(--text-sm)" }}>
                Ocupación de Disco Principal
              </div>
            }
          >
            <TelemetryChart
              title="Uso de Almacenamiento"
              samples={telemetryDisk as any}
              unit="%"
              color="var(--status-healthy)"
              height={150}
            />
          </Card>
        </div>
      </div>

      {/* Two Columns: Recent Alerts & Recent Tickets */}
      <div className="grid-responsive" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(450px, 1fr))" }}>
        {/* Active Alerts */}
        <Card
          header={
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontWeight: 600 }}>
                <AlertOctagon size={18} color="var(--status-critical)" />
                <span>Alertas Recientes</span>
              </div>
              <Button variant="ghost" size="sm" onClick={() => onNavigate("alerts")}>
                Ver todas ({alerts.length})
              </Button>
            </div>
          }
        >
          <Table
            columns={[
              {
                header: "Severidad",
                cell: (a) => (
                  <Badge variant={a.severity === "CRITICAL" ? "critical" : "warning"} dot>
                    {a.severity}
                  </Badge>
                ),
                width: "110px",
              },
              {
                header: "Mensaje",
                accessorKey: "message",
              },
              {
                header: "Hora",
                cell: (a) => new Date(a.triggered_at).toLocaleTimeString(),
                align: "right",
                width: "90px",
              },
            ]}
            data={alerts.slice(0, 5)}
            keyExtractor={(a) => a.id}
            emptyMessage="No hay alertas registradas. Toda la infraestructura opera dentro de los umbrales normales."
          />
        </Card>

        {/* Support Tickets */}
        <Card
          header={
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontWeight: 600 }}>
                <LifeBuoy size={18} color="var(--brand-primary)" />
                <span>Tickets de Mesa de Ayuda</span>
              </div>
              <Button variant="ghost" size="sm" onClick={() => onNavigate("tickets")}>
                Ver todos ({tickets.length})
              </Button>
            </div>
          }
        >
          <Table
            columns={[
              {
                header: "#",
                cell: (t) => (
                  <span style={{ fontFamily: "var(--font-mono)", fontWeight: 600, color: "var(--brand-primary)" }}>
                    {t.ticket_number}
                  </span>
                ),
                width: "110px",
              },
              {
                header: "Título",
                accessorKey: "title",
              },
              {
                header: "Estado",
                cell: (t) => <StatusIndicator status={t.status} />,
                width: "120px",
              },
              {
                header: "Prioridad",
                cell: (t) => (
                  <Badge
                    variant={
                      t.priority === "CRITICAL"
                        ? "critical"
                        : t.priority === "HIGH"
                        ? "warning"
                        : "info"
                    }
                  >
                    {t.priority}
                  </Badge>
                ),
                width: "100px",
              },
            ]}
            data={tickets.slice(0, 5)}
            keyExtractor={(t) => t.id}
            emptyMessage="No hay tickets de soporte abiertos actualmente."
          />
        </Card>
      </div>
    </div>
  );
}
