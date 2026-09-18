import { useState, useEffect, useCallback } from "react";
import { devicesApi } from "@/api/devices";
import { ticketsApi } from "@/api/tickets";
import { useAuth } from "@/context/AuthContext";
import { useNotification } from "@/context/NotificationContext";
import type { DeviceResponse } from "@/types/devices";
import type { TicketResponse } from "@/types/tickets";
import { Card } from "@/components/common/Card";
import { Button } from "@/components/common/Button";
import { Badge } from "@/components/common/Badge";
import { Table } from "@/components/common/Table";
import { StatusIndicator } from "@/components/metrics/StatusIndicator";
import { CreateTicketModal } from "@/views/tickets/CreateTicketModal";
import { getDeviceStatus } from "@/utils/deviceStatus";
import {
  LifeBuoy,
  Plus,
  Monitor,
  ShieldCheck,
  Headphones,
  RefreshCw,
  Activity,
  CheckCircle2,
  Clock,
} from "lucide-react";

export function ClientPortalView() {
  const { user } = useAuth();
  const { success, error } = useNotification();
  const [device, setDevice] = useState<DeviceResponse | null>(null);
  const [tickets, setTickets] = useState<TicketResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isTicketModalOpen, setIsTicketModalOpen] = useState(false);
  const [isAssistanceRequested, setIsAssistanceRequested] = useState(false);
  const [isAssistanceSubmitting, setIsAssistanceSubmitting] = useState(false);

  const loadPortalData = useCallback(async () => {
    setIsLoading(true);
    try {
      const [devList, tckList] = await Promise.all([
        devicesApi.list({ limit: 10 }).catch(() => ({ items: [] })),
        ticketsApi.list({ limit: 50 }).catch(() => ({ items: [] })),
      ]);

      if (devList.items.length > 0) {
        setDevice(devList.items[0] || null);
      }
      setTickets(tckList.items);
    } catch {
      // handled gracefully
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadPortalData();
  }, [loadPortalData]);

  const handleRequestAssistance = async () => {
    setIsAssistanceSubmitting(true);
    try {
      const created = await ticketsApi.create({
        title: `Solicitud prioritaria de asistencia técnica - ${user?.full_name || user?.email || "Usuario"}`,
        description: `El usuario ${user?.full_name || user?.email} solicita contacto técnico para el equipo ${device?.hostname || "estación de trabajo"}.\n\nCoordinar la atención mediante este ticket. Esta solicitud no inicia una sesión remota ni autoriza comandos.`,
        priority: "HIGH",
        device_id: device?.id || null,
      });
      setTickets((prev) => [created, ...prev]);
      setIsAssistanceRequested(true);
      success(
        "Solicitud de asistencia registrada",
        `Ticket #${created.ticket_number} creado. El equipo de soporte recibió la solicitud.`
      );
    } catch {
      error(
        "No se pudo registrar la solicitud",
        "Intenta nuevamente o crea un ticket de soporte manual."
      );
    } finally {
      setIsAssistanceSubmitting(false);
    }
  };

  const isOnline = device ? getDeviceStatus(device) === "ONLINE" : false;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-6)" }}>
      {/* Top Banner */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: "1rem",
          padding: "1.5rem",
          borderRadius: "var(--radius-xl)",
          background: "linear-gradient(135deg, rgba(59, 130, 246, 0.12) 0%, rgba(16, 185, 129, 0.06) 100%)",
          border: "1px solid rgba(59, 130, 246, 0.2)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
          <div
            style={{
              width: "52px",
              height: "52px",
              borderRadius: "var(--radius-lg)",
              backgroundColor: "var(--brand-primary)",
              color: "#fff",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <Headphones size={26} />
          </div>
          <div>
            <h2 style={{ fontSize: "var(--text-xl)", fontWeight: 700 }}>
              Portal de Autoservicio & Soporte
            </h2>
            <p style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)", marginTop: "0.25rem" }}>
              Bienvenido, <strong>{user?.full_name || user?.email}</strong>. Monitorea la salud de tu equipo y gestiona tus tickets de soporte.
            </p>
          </div>
        </div>

        {/* Quick Actions */}
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
          <Button
            variant="secondary"
            onClick={handleRequestAssistance}
            disabled={isAssistanceRequested || isAssistanceSubmitting}
            isLoading={isAssistanceSubmitting}
            leftIcon={isAssistanceRequested ? <CheckCircle2 size={16} color="var(--status-healthy)" /> : <Headphones size={16} />}
          >
            {isAssistanceRequested ? "Solicitud registrada" : "Solicitar ayuda técnica"}
          </Button>

          <Button
            variant="primary"
            onClick={() => setIsTicketModalOpen(true)}
            leftIcon={<Plus size={16} />}
          >
            Crear Ticket de Soporte
          </Button>
        </div>
      </div>

      {/* Registered support request banner */}
      {isAssistanceRequested && (
        <div
          style={{
            padding: "1rem 1.25rem",
            borderRadius: "var(--radius-lg)",
            backgroundColor: "rgba(16, 185, 129, 0.08)",
            border: "1px solid rgba(16, 185, 129, 0.3)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            flexWrap: "wrap",
            gap: "1rem",
            boxShadow: "0 4px 15px rgba(16, 185, 129, 0.1)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
            <div
              className="status-dot healthy pulse"
              style={{ width: "12px", height: "12px" }}
            />
            <div>
              <div style={{ fontSize: "var(--text-sm)", fontWeight: 700, color: "var(--status-healthy)" }}>
                Solicitud de asistencia registrada
              </div>
              <div style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)", marginTop: "2px" }}>
                Soporte recibió el ticket para <strong>{device?.hostname}</strong>. Esto no inicia una sesión remota ni concede control del equipo.
              </div>
            </div>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setIsAssistanceRequested(false)}
              style={{ color: "var(--status-critical)" }}
            >
              Cerrar aviso
            </Button>
          </div>
        </div>
      )}

      {/* Device Health & Overview Card */}
      {device ? (
        <Card
          header={
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                <Monitor size={18} color="var(--brand-primary)" />
                <span style={{ fontWeight: 600, fontSize: "var(--text-sm)" }}>
                  Mi Estación de Trabajo: {device.hostname}
                </span>
              </div>
              <StatusIndicator status={getDeviceStatus(device)} />
            </div>
          }
        >
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "1rem" }}>
            <div style={{ padding: "0.75rem", backgroundColor: "var(--bg-surface-elevated)", borderRadius: "var(--radius-md)", border: "1px solid var(--border-subtle)" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "0.375rem", color: "var(--text-muted)", fontSize: "var(--text-2xs)" }}>
                <Activity size={12} color="var(--status-healthy)" />
                <span>ESTADO DE CONEXIÓN</span>
              </div>
              <div style={{ marginTop: "0.25rem", fontWeight: 700, fontSize: "var(--text-sm)", color: isOnline ? "var(--status-healthy)" : "var(--text-muted)" }}>
                {isOnline ? "En Línea & Monitoreado" : "Desconectado"}
              </div>
            </div>

            <div style={{ padding: "0.75rem", backgroundColor: "var(--bg-surface-elevated)", borderRadius: "var(--radius-md)", border: "1px solid var(--border-subtle)" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "0.375rem", color: "var(--text-muted)", fontSize: "var(--text-2xs)" }}>
                <Clock size={12} color="var(--brand-primary)" />
                <span>ÚLTIMA SINCRONIZACIÓN</span>
              </div>
              <div style={{ marginTop: "0.25rem", fontWeight: 600, fontSize: "var(--text-xs)" }}>
                {device.last_seen_at ? new Date(device.last_seen_at).toLocaleTimeString() : "Sin datos"}
              </div>
            </div>

            <div style={{ padding: "0.75rem", backgroundColor: "var(--bg-surface-elevated)", borderRadius: "var(--radius-md)", border: "1px solid var(--border-subtle)" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "0.375rem", color: "var(--text-muted)", fontSize: "var(--text-2xs)" }}>
                <ShieldCheck size={12} color="var(--status-healthy)" />
                <span>PROTECCIÓN ACTIVA</span>
              </div>
              <div style={{ marginTop: "0.25rem", fontWeight: 600, fontSize: "var(--text-xs)", color: "var(--text-primary)" }}>
                Agente Autónomo v1.0 • Seguro
              </div>
            </div>
          </div>
        </Card>
      ) : null}

      {/* Support Tickets Section */}
      <Card
        header={
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontWeight: 600 }}>
              <LifeBuoy size={18} color="var(--brand-primary)" />
              <span>Mis Solicitudes & Tickets de Soporte</span>
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={loadPortalData}
              isLoading={isLoading}
              leftIcon={<RefreshCw size={14} />}
            >
              Actualizar
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
              header: "Asunto / Incidencia",
              accessorKey: "title",
            },
            {
              header: "Estado",
              cell: (t) => <StatusIndicator status={t.status} />,
              width: "140px",
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
            {
              header: "Fecha de Creación",
              cell: (t) => new Date(t.created_at).toLocaleString(),
              width: "180px",
            },
          ]}
          data={tickets}
          keyExtractor={(t) => t.id}
          emptyTitle="No tienes tickets abiertos"
          emptyMessage="Si experimentas alguna falla técnica o lentitud, haz clic en 'Crear Ticket de Soporte'."
        />
      </Card>

      {/* Create Ticket Modal */}
      <CreateTicketModal
        isOpen={isTicketModalOpen}
        deviceId={device?.id ?? null}
        onClose={() => setIsTicketModalOpen(false)}
        onCreated={() => loadPortalData()}
      />
    </div>
  );
}
