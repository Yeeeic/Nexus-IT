import { useEffect, useState, useCallback } from "react";
import { metricsApi } from "@/api/metrics";
import type { AlertResponse, AlertRuleResponse } from "@/types/metrics";
import { Table } from "@/components/common/Table";
import { Button } from "@/components/common/Button";
import { Badge } from "@/components/common/Badge";
import { Tabs } from "@/components/common/Tabs";
import { Card } from "@/components/common/Card";
import { AlertRulesModal } from "./AlertRulesModal";
import { useNotification } from "@/context/NotificationContext";
import { AlertOctagon, Plus, RefreshCw, Sliders, CheckCircle2 } from "lucide-react";

export function AlertsView() {
  const { error: notifyError } = useNotification();
  const [alerts, setAlerts] = useState<AlertResponse[]>([]);
  const [rules, setRules] = useState<AlertRuleResponse[]>([]);
  const [activeTab, setActiveTab] = useState<string>("open_alerts");
  const [isLoading, setIsLoading] = useState(true);
  const [isRuleModalOpen, setIsRuleModalOpen] = useState(false);

  const loadData = useCallback(async () => {
    setIsLoading(true);
    try {
      const [alts, rls] = await Promise.all([
        metricsApi.listAlerts({ limit: 100 }).catch(() => ({ items: [] })),
        metricsApi.listAlertRules().catch(() => ({ items: [] })),
      ]);
      setAlerts(alts.items);
      setRules(rls.items);
    } catch (err: any) {
      notifyError("Error al cargar alertas", err.message);
    } finally {
      setIsLoading(false);
    }
  }, [notifyError]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const openAlerts = alerts.filter((a) => a.status === "OPEN" || a.status === "ACKNOWLEDGED");
  const resolvedAlerts = alerts.filter((a) => a.status === "RESOLVED" || a.status === "SUPPRESSED");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-6)" }}>
      {/* Header & Actions */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "1rem" }}>
        <div>
          <h2 style={{ fontSize: "var(--text-xl)", fontWeight: 700 }}>Centro de Alertas & Umbrales</h2>
          <p style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)", marginTop: "0.25rem" }}>
            Monitoreo proactivo, prevención de flapping y reglas de incidentes automáticas
          </p>
        </div>

        <div style={{ display: "flex", gap: "0.5rem" }}>
          <Button
            variant="secondary"
            size="sm"
            onClick={loadData}
            isLoading={isLoading}
            leftIcon={<RefreshCw size={14} />}
          >
            Actualizar
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => setIsRuleModalOpen(true)}
            leftIcon={<Plus size={14} />}
          >
            Nueva Regla de Alerta
          </Button>
        </div>
      </div>

      {/* Tabs */}
      <Tabs
        activeTab={activeTab}
        onChange={setActiveTab}
        tabs={[
          { id: "open_alerts", label: "Alertas Activas", count: openAlerts.length, icon: <AlertOctagon size={16} /> },
          { id: "resolved_alerts", label: "Historial de Incidentes", count: resolvedAlerts.length, icon: <CheckCircle2 size={16} /> },
          { id: "rules", label: "Reglas de Alerta", count: rules.length, icon: <Sliders size={16} /> },
        ]}
      />

      {/* Tab 1: Active Alerts */}
      {activeTab === "open_alerts" && (
        <Card>
          <Table
            columns={[
              {
                header: "Severidad",
                cell: (a) => (
                  <Badge variant={a.severity === "CRITICAL" ? "critical" : a.severity === "WARNING" ? "warning" : "info"} dot>
                    {a.severity}
                  </Badge>
                ),
                width: "120px",
              },
              {
                header: "Mensaje del Incidente",
                accessorKey: "message",
              },
              {
                header: "Dispositivo",
                cell: (a) => (
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--text-xs)" }}>
                    {a.device_id.substring(0, 8)}...
                  </span>
                ),
                width: "140px",
              },
              {
                header: "Estado",
                cell: (a) => (
                  <Badge variant={a.status === "OPEN" ? "critical" : "warning"}>
                    {a.status}
                  </Badge>
                ),
                width: "120px",
              },
              {
                header: "Hora de Activación",
                cell: (a) => new Date(a.triggered_at).toLocaleString(),
                width: "180px",
              },
            ]}
            data={openAlerts}
            keyExtractor={(a) => a.id}
            emptyTitle="Sin alertas activas"
            emptyMessage="Toda la flota se encuentra operando dentro de los parámetros esperados."
          />
        </Card>
      )}

      {/* Tab 2: Resolved Alerts */}
      {activeTab === "resolved_alerts" && (
        <Card>
          <Table
            columns={[
              {
                header: "Severidad",
                cell: (a) => (
                  <Badge variant="healthy" dot>
                    RESUELTA ({a.severity})
                  </Badge>
                ),
                width: "150px",
              },
              {
                header: "Incidente",
                accessorKey: "message",
              },
              {
                header: "Activación",
                cell: (a) => new Date(a.triggered_at).toLocaleString(),
                width: "170px",
              },
              {
                header: "Resolución",
                cell: (a) => (a.resolved_at ? new Date(a.resolved_at).toLocaleString() : "-"),
                width: "170px",
              },
            ]}
            data={resolvedAlerts}
            keyExtractor={(a) => a.id}
            emptyMessage="No hay incidentes previos archivados."
          />
        </Card>
      )}

      {/* Tab 3: Configured Rules */}
      {activeTab === "rules" && (
        <Card>
          <Table
            columns={[
              {
                header: "Nombre de Regla",
                accessorKey: "name",
              },
              {
                header: "Métrica",
                cell: (r) => <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--text-xs)" }}>{r.metric_name}</span>,
              },
              {
                header: "Condición",
                cell: (r) => (
                  <span style={{ fontWeight: 600 }}>
                    {r.operator} {r.threshold_value}% ({r.duration_seconds}s)
                  </span>
                ),
              },
              {
                header: "Severidad",
                cell: (r) => (
                  <Badge variant={r.severity === "CRITICAL" ? "critical" : "warning"}>
                    {r.severity}
                  </Badge>
                ),
              },
              {
                header: "Estado",
                cell: (r) => (
                  <Badge variant={r.is_enabled ? "healthy" : "offline"}>
                    {r.is_enabled ? "Activa" : "Inactiva"}
                  </Badge>
                ),
              },
            ]}
            data={rules}
            keyExtractor={(r) => r.id}
            emptyTitle="Sin reglas configuradas"
            emptyMessage="Haga clic en 'Nueva Regla de Alerta' para definir umbrales automáticos."
          />
        </Card>
      )}

      {/* Alert Rule Creation Modal */}
      <AlertRulesModal
        isOpen={isRuleModalOpen}
        onClose={() => setIsRuleModalOpen(false)}
        onRuleCreated={loadData}
      />
    </div>
  );
}
