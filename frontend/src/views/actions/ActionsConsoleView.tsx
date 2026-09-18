import React, { useEffect, useState, useCallback } from "react";
import { actionsApi } from "@/api/actions";
import { devicesApi } from "@/api/devices";
import type { ActionResponse, ActionCatalogType } from "@/types/actions";
import type { DeviceResponse } from "@/types/devices";
import { StatusIndicator } from "@/components/metrics/StatusIndicator";
import { Table } from "@/components/common/Table";
import { Button } from "@/components/common/Button";
import { Select } from "@/components/common/Select";
import { Input } from "@/components/common/Input";
import { Card } from "@/components/common/Card";
import { Modal } from "@/components/common/Modal";
import { ActionApprovalModal } from "./ActionApprovalModal";
import { useNotification } from "@/context/NotificationContext";
import { useAuth } from "@/context/AuthContext";
import { Terminal, Plus, RefreshCw, CheckCircle, ShieldCheck } from "lucide-react";

export const ACTION_CATALOG_OPTIONS: Array<{
  value: ActionCatalogType;
  label: string;
}> = [
  { value: "reboot_system", label: "Reiniciar Sistema (reboot_system) - Requiere Aprobación" },
  { value: "restart_service", label: "Reiniciar Servicio (restart_service)" },
  { value: "collect_extended_diagnostics", label: "Recolectar Diagnóstico (collect_extended_diagnostics)" },
  { value: "flush_dns", label: "Vaciar Caché DNS (flush_dns)" },
];

export function ActionsConsoleView() {
  const { success, error: notifyError } = useNotification();
  const { hasPermission } = useAuth();
  const [devices, setDevices] = useState<DeviceResponse[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState<string>("");
  const [actions, setActions] = useState<ActionResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [approvalTarget, setApprovalTarget] = useState<ActionResponse | null>(null);

  // New Action Modal
  const [isNewActionOpen, setIsNewActionOpen] = useState(false);
  const [actionType, setActionType] = useState<ActionCatalogType>("reboot_system");
  const [paramValue, setParamValue] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const loadDevicesAndActions = useCallback(async () => {
    setIsLoading(true);
    try {
      const devResponse = await devicesApi.list({ limit: 100 });
      setDevices(devResponse.items);
      const targetDevId = selectedDeviceId || devResponse.items[0]?.id;
      if (targetDevId) {
        if (!selectedDeviceId) setSelectedDeviceId(targetDevId);
        const actionResponse = await actionsApi.listByDevice(targetDevId);
        setActions(actionResponse.items);
      } else {
        setActions([]);
      }
    } catch (err: any) {
      notifyError("Error al cargar acciones remotas", err.message);
    } finally {
      setIsLoading(false);
    }
  }, [notifyError, selectedDeviceId]);

  useEffect(() => {
    loadDevicesAndActions();
  }, [loadDevicesAndActions]);

  const handleDeviceChange = async (deviceId: string) => {
    setSelectedDeviceId(deviceId);
    setIsLoading(true);
    try {
      const resp = await actionsApi.listByDevice(deviceId);
      setActions(resp.items);
    } catch (err: any) {
      notifyError("Error al consultar acciones del equipo", err.message);
    } finally {
      setIsLoading(false);
    }
  };

  const handleCreateAction = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedDeviceId) return;

    setIsSubmitting(true);
    try {
      const parameters: Record<string, unknown> = {};
      if (actionType === "restart_service") {
        parameters["service_name"] = paramValue || "nginx";
      }

      const created = await actionsApi.create(selectedDeviceId, {
        action_name: actionType,
        parameters,
      });

      success("Solicitud de acción registrada", `Acción: ${created.action_name}`);
      setIsNewActionOpen(false);
      const resp = await actionsApi.listByDevice(selectedDeviceId);
      setActions(resp.items);
    } catch (err: any) {
      notifyError("Error al despachar acción", err.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-6)" }}>
      {/* Header & Actions */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "1rem" }}>
        <div>
          <h2 style={{ fontSize: "var(--text-xl)", fontWeight: 700 }}>Consola de Acciones Remotas</h2>
          <p style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)", marginTop: "0.25rem" }}>
            Catálogo cerrado de operaciones seguras firmadas con Ed25519 y trazabilidad append-only
          </p>
        </div>

        <div style={{ display: "flex", gap: "0.5rem" }}>
          <Button
            variant="secondary"
            size="sm"
            onClick={loadDevicesAndActions}
            isLoading={isLoading}
            leftIcon={<RefreshCw size={14} />}
          >
            Actualizar
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => setIsNewActionOpen(true)}
            disabled={devices.length === 0}
            leftIcon={<Plus size={14} />}
          >
            Nueva Acción Remota
          </Button>
        </div>
      </div>

      {/* Security Guarantee Card */}
      <Card style={{ borderLeft: "4px solid var(--brand-primary)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          <ShieldCheck size={24} color="var(--brand-primary)" />
          <div style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)" }}>
            <strong>Protección de Ejecución:</strong> No se admiten comandos arbitrarios. El agente únicamente ejecuta acciones del catálogo cerrado previamente autorizadas, con token de un solo uso (*anti-replay*) y firma criptográfica asimétrica del servidor.
          </div>
        </div>
      </Card>

      {/* Device Selector for Actions */}
      <div className="nexus-card" style={{ padding: "var(--space-3) var(--space-4)", display: "flex", alignItems: "center", gap: "1rem" }}>
        <label style={{ fontSize: "var(--text-xs)", fontWeight: 600, color: "var(--text-secondary)" }}>
          Filtrar por Dispositivo:
        </label>
        <div style={{ width: "320px" }}>
          <Select
            value={selectedDeviceId}
            onChange={(e) => handleDeviceChange(e.target.value)}
            options={devices.map((d) => ({
              value: d.id,
              label: `${d.hostname} ${d.display_name ? `(${d.display_name})` : ""}`,
            }))}
          />
        </div>
      </div>

      {/* Actions Table */}
      <Card>
        <Table
          columns={[
            {
              header: "Tipo de Acción",
              cell: (a) => (
                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                  <Terminal size={16} color="var(--brand-primary)" />
                  <span style={{ fontFamily: "var(--font-mono)", fontWeight: 600, color: "var(--text-primary)" }}>
                    {a.action_name}
                  </span>
                </div>
              ),
              width: "180px",
            },
            {
              header: "ID de Acción",
              cell: (a) => <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--text-xs)" }}>{a.id.substring(0, 8)}...</span>,
              width: "140px",
            },
            {
              header: "Estado",
              cell: (a) => <StatusIndicator status={a.status} />,
              width: "150px",
            },
            {
              header: "Firma Criptográfica",
              cell: (a) => (
                <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--text-2xs)", color: a.signature ? "var(--status-healthy)" : "var(--status-warning)" }}>
                  {a.signature ? `Ed25519 (v${a.key_version || 1})` : "Pendiente de Aprobación"}
                </span>
              ),
              width: "170px",
            },
            {
              header: "Emisión",
              cell: (a) => new Date(a.issued_at).toLocaleString(),
              width: "180px",
            },
            {
              header: "Acción",
              align: "right",
              width: "130px",
              cell: (a) => {
                if (a.status === "PENDING_APPROVAL" && hasPermission("actions:approve_admin")) {
                  return (
                    <Button
                      variant="primary"
                      size="sm"
                      onClick={() => setApprovalTarget(a)}
                      leftIcon={<CheckCircle size={14} />}
                      style={{ padding: "4px 8px" }}
                    >
                      Aprobar
                    </Button>
                  );
                }
                return null;
              },
            },
          ]}
          data={actions}
          keyExtractor={(a) => a.id}
          emptyTitle="Sin acciones registradas para este equipo"
          emptyMessage="No se han despachado operaciones remotas recientemente en el dispositivo seleccionado."
        />
      </Card>

      {/* New Action Request Modal */}
      <Modal
        isOpen={isNewActionOpen}
        onClose={() => setIsNewActionOpen(false)}
        title="Solicitar Acción Remota"
        description="Seleccione el equipo destino y el comando autorizado del catálogo"
      >
        <form onSubmit={handleCreateAction} style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          <Select
            label="Dispositivo Destino"
            value={selectedDeviceId}
            onChange={(e) => setSelectedDeviceId(e.target.value)}
            options={devices.map((d) => ({
              value: d.id,
              label: `${d.hostname} ${d.display_name ? `(${d.display_name})` : ""}`,
            }))}
          />

          <Select
            label="Acción del Catálogo Cerrado"
            value={actionType}
            onChange={(e) => setActionType(e.target.value as ActionCatalogType)}
            options={ACTION_CATALOG_OPTIONS}
          />

          {actionType === "restart_service" && (
            <Input
              label="Nombre del Servicio a Reiniciar"
              placeholder="nginx / postgresql / docker"
              value={paramValue}
              onChange={(e) => setParamValue(e.target.value)}
              required
            />
          )}

          <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem", marginTop: "1rem" }}>
            <Button type="button" variant="ghost" onClick={() => setIsNewActionOpen(false)}>
              Cancelar
            </Button>
            <Button type="submit" variant="primary" isLoading={isSubmitting}>
              Enviar Solicitud
            </Button>
          </div>
        </form>
      </Modal>

      {/* Approval Modal */}
      {approvalTarget && (
        <ActionApprovalModal
          action={approvalTarget}
          isOpen={Boolean(approvalTarget)}
          onClose={() => setApprovalTarget(null)}
          onProcessed={loadDevicesAndActions}
        />
      )}
    </div>
  );
}
