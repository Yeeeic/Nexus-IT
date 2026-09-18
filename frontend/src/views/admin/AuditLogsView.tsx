import { useEffect, useState, useCallback } from "react";
import { adminApi } from "@/api/admin";
import type { AuditLogResponse } from "@/types/admin";
import { Table } from "@/components/common/Table";
import { Button } from "@/components/common/Button";
import { Badge } from "@/components/common/Badge";
import { Card } from "@/components/common/Card";
import { useNotification } from "@/context/NotificationContext";
import { RefreshCw, FileText } from "lucide-react";

export function AuditLogsView() {
  const { error: notifyError } = useNotification();
  const [logs, setLogs] = useState<AuditLogResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const loadLogs = useCallback(async () => {
    setIsLoading(true);
    try {
      const resp = await adminApi.listAuditLogs({ limit: 100 });
      setLogs(resp.items);
    } catch (err: any) {
      notifyError("Error al cargar registros de auditoría", err.message);
    } finally {
      setIsLoading(false);
    }
  }, [notifyError]);

  useEffect(() => {
    loadLogs();
  }, [loadLogs]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <p style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)" }}>
          Registro append-only inmutable de todas las mutaciones, accesos y eventos de seguridad
        </p>
        <Button
          variant="secondary"
          size="sm"
          onClick={loadLogs}
          isLoading={isLoading}
          leftIcon={<RefreshCw size={14} />}
        >
          Actualizar
        </Button>
      </div>

      <Card>
        <Table
          columns={[
            {
              header: "Fecha / Hora",
              cell: (l) => new Date(l.created_at).toLocaleString(),
              width: "180px",
            },
            {
              header: "Actor",
              cell: (l) => (
                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                  <Badge variant={l.actor_type === "SYSTEM" ? "info" : l.actor_type === "AGENT" ? "info" : "healthy"}>
                    {l.actor_type}
                  </Badge>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--text-xs)" }}>
                    {l.actor_id ? `${l.actor_id.substring(0, 8)}...` : "Sistema"}
                  </span>
                </div>
              ),
              width: "200px",
            },
            {
              header: "Acción Ejecutada",
              cell: (l) => (
                <div style={{ display: "flex", alignItems: "center", gap: "0.375rem" }}>
                  <FileText size={14} color="var(--brand-primary)" />
                  <strong style={{ fontFamily: "var(--font-mono)", fontSize: "var(--text-xs)" }}>{l.action}</strong>
                </div>
              ),
              width: "220px",
            },
            {
              header: "Recurso",
              cell: (l) => (
                <span style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)" }}>
                  {l.resource_type} {l.resource_id ? `(${l.resource_id.substring(0, 8)}...)` : ""}
                </span>
              ),
              width: "180px",
            },
            {
              header: "Resultado",
              cell: (l) => (
                <Badge
                  variant={
                    l.status === "SUCCESS"
                      ? "healthy"
                      : l.status === "DENIED"
                      ? "warning"
                      : "critical"
                  }
                >
                  {l.status}
                </Badge>
              ),
              width: "110px",
            },
          ]}
          data={logs}
          keyExtractor={(l) => l.id}
          emptyTitle="Sin eventos de auditoría"
          emptyMessage="No se han registrado eventos recientemente en la organización."
        />
      </Card>
    </div>
  );
}
