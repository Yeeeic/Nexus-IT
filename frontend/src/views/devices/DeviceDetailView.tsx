import { useEffect, useState, useCallback, useRef } from "react";
import { devicesApi } from "@/api/devices";
import { metricsApi } from "@/api/metrics";
import { adminApi } from "@/api/admin";
import type { DeviceResponse, InventoryResponse } from "@/types/devices";
import type { TelemetrySampleResponse } from "@/types/metrics";
import type { UserSummaryResponse } from "@/types/admin";
import { StatusIndicator } from "@/components/metrics/StatusIndicator";
import { TelemetryChart } from "@/components/metrics/TelemetryChart";
import { Card } from "@/components/common/Card";
import { Tabs } from "@/components/common/Tabs";
import { Table } from "@/components/common/Table";
import { Button } from "@/components/common/Button";
import { Select } from "@/components/common/Select";
import { Skeleton } from "@/components/common/Skeleton";
import { Modal } from "@/components/common/Modal";
import { DeviceEnrollModal } from "./DeviceEnrollModal";
import { RemoteScreenViewer } from "@/components/remote/RemoteScreenViewer";
import { WebTerminalView } from "@/components/remote/WebTerminalView";
import { useNotification } from "@/context/NotificationContext";
import { getDeviceStatus } from "@/utils/deviceStatus";
import {
  ArrowLeft,
  Key,
  Cpu,
  Activity,
  Settings,
  RefreshCw,
  UserCheck,
  Monitor,
  Terminal,
  Unplug,
  Trash2,
  AlertTriangle,
} from "lucide-react";

export interface DeviceDetailViewProps {
  deviceId: string;
  onBack: () => void;
}

export function DeviceDetailView({ deviceId, onBack }: DeviceDetailViewProps) {
  const { success, error: notifyError } = useNotification();
  const [device, setDevice] = useState<DeviceResponse | null>(null);
  const [inventory, setInventory] = useState<InventoryResponse | null>(null);
  const [users, setUsers] = useState<UserSummaryResponse[]>([]);
  const [selectedUserId, setSelectedUserId] = useState<string>("");
  const [activeTab, setActiveTab] = useState<string>("telemetry");
  const [cpuSamples, setCpuSamples] = useState<TelemetrySampleResponse[]>([]);
  const [memSamples, setMemSamples] = useState<TelemetrySampleResponse[]>([]);
  const [diskSamples, setDiskSamples] = useState<TelemetrySampleResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isAssigning, setIsAssigning] = useState(false);
  const [isEnrollOpen, setIsEnrollOpen] = useState(false);
  const isFetchingRef = useRef(false);

  const loadDetails = useCallback(async (isInitial = false) => {
    if (isFetchingRef.current) return;
    isFetchingRef.current = true;
    if (isInitial) setIsLoading(true);
    try {
      const [devDetail, inv, cpu, mem, disk, uList] = await Promise.all([
        devicesApi.getById(deviceId),
        devicesApi.getInventory(deviceId).catch(() => null),
        metricsApi.getTelemetry(deviceId, { metric_name: "system.cpu_percent", limit: 30 })
          .catch(() => metricsApi.getTelemetry(deviceId, { metric_name: "system.cpu.usage", limit: 30 }))
          .catch(() => ({ items: [] })),
        metricsApi.getTelemetry(deviceId, { metric_name: "system.memory_used_percent", limit: 30 })
          .catch(() => metricsApi.getTelemetry(deviceId, { metric_name: "system.memory.usage", limit: 30 }))
          .catch(() => ({ items: [] })),
        metricsApi.getTelemetry(deviceId, { metric_name: "system.disk_used_percent", limit: 30 })
          .catch(() => metricsApi.getTelemetry(deviceId, { metric_name: "system.disk.usage", limit: 30 }))
          .catch(() => ({ items: [] })),
        adminApi.listUsers({ limit: 100 }).catch(() => ({ items: [] })),
      ]);

      setDevice(devDetail);
      setInventory(inv);
      setCpuSamples(cpu.items.slice().reverse());
      setMemSamples(mem.items.slice().reverse());
      setDiskSamples(disk.items.slice().reverse());
      setUsers(uList.items);
      if (uList.items.length > 0 && !selectedUserId) {
        setSelectedUserId(uList.items[0]?.id || "");
      }
    } catch (err: any) {
      if (isInitial) {
        notifyError("Error al cargar detalles del dispositivo", err.message);
      }
    } finally {
      isFetchingRef.current = false;
      setIsLoading(false);
    }
  }, [deviceId, notifyError, selectedUserId]);

  useEffect(() => {
    loadDetails(true);
    const interval = setInterval(() => {
      if (typeof document !== "undefined" && document.visibilityState === "visible") {
        loadDetails(false);
      }
    }, 6000); // 6s fast poll for live telemetry view
    return () => clearInterval(interval);
  }, [loadDetails]);

  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

  const handleAssignUser = async () => {
    if (!selectedUserId) return;
    setIsAssigning(true);
    try {
      await devicesApi.assignUser(deviceId, selectedUserId);
      success("Dispositivo asignado exitosamente al usuario");
      await loadDetails();
    } catch (err: any) {
      notifyError("Error al asignar dispositivo", err.message);
    } finally {
      setIsAssigning(false);
    }
  };

  const handleDisconnect = async () => {
    try {
      await devicesApi.disconnect(deviceId);
      success("Dispositivo Desconectado", `Se han revocado las credenciales activas del agente en ${device?.hostname}.`);
      await loadDetails();
    } catch (err: any) {
      notifyError("Error al desconectar dispositivo", err.message);
    }
  };

  const handleDeleteDevice = async () => {
    setIsDeleting(true);
    try {
      await devicesApi.delete(deviceId);
      success("Dispositivo Desaprovisionado", `El equipo ${device?.hostname} fue eliminado.`);
      onBack();
    } catch (err: any) {
      notifyError("Error al eliminar dispositivo", err.message);
    } finally {
      setIsDeleting(false);
    }
  };

  if (isLoading && !device) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
        <Skeleton height="80px" />
        <Skeleton height="300px" />
      </div>
    );
  }

  if (!device) {
    return (
      <div style={{ textAlign: "center", padding: "3rem" }}>
        <p>No se encontró el dispositivo especificado.</p>
        <Button variant="secondary" onClick={onBack} style={{ marginTop: "1rem" }}>
          Volver a la lista
        </Button>
      </div>
    );
  }

  const hardware = inventory?.hardware as any;
  const isOnline = getDeviceStatus(device) === "ONLINE";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-6)" }}>
      {/* Header with Breadcrumb, Status, and Actions */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          <Button variant="ghost" size="sm" onClick={onBack} leftIcon={<ArrowLeft size={16} />}>
            Volver
          </Button>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
              <h2 style={{ fontSize: "var(--text-xl)", fontWeight: 700 }}>{device.hostname}</h2>
              <StatusIndicator status={getDeviceStatus(device)} />
            </div>
            <div style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)", marginTop: "0.25rem", display: "flex", gap: "1rem", flexWrap: "wrap" }}>
              {device.display_name && (
                <span>Etiqueta: <strong style={{ color: "var(--text-primary)" }}>{device.display_name}</strong></span>
              )}
              <span>Último contacto: <strong style={{ color: "var(--text-primary)" }}>{device.last_seen_at ? new Date(device.last_seen_at).toLocaleString() : "Nunca"}</strong></span>
              <span>Registrado: <strong style={{ color: "var(--text-primary)" }}>{new Date(device.created_at).toLocaleDateString()}</strong></span>
            </div>
          </div>
        </div>

        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => loadDetails(true)}
            leftIcon={<RefreshCw size={14} />}
          >
            Actualizar
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={handleDisconnect}
            leftIcon={<Unplug size={14} />}
            title="Desconectar y rotar credenciales del agente"
          >
            Desconectar
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => setIsEnrollOpen(true)}
            leftIcon={<Key size={14} />}
          >
            Token de Agente
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setIsDeleteModalOpen(true)}
            style={{ color: "var(--status-critical)" }}
            title="Desaprovisionar dispositivo de la flota"
          >
            <Trash2 size={14} />
          </Button>
        </div>
      </div>

      {/* Delete Device Modal */}
      {isDeleteModalOpen && (
        <Modal
          isOpen={isDeleteModalOpen}
          onClose={() => setIsDeleteModalOpen(false)}
          title="⚠️ Confirmar Desaprovisionamiento"
          maxWidth="460px"
        >
          <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", color: "var(--status-critical)" }}>
              <AlertTriangle size={24} />
              <div style={{ fontWeight: 600, fontSize: "var(--text-sm)" }}>
                ¿Eliminar el equipo {device.hostname}?
              </div>
            </div>
            <p style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)", lineHeight: 1.4 }}>
              Esta acción eliminará de forma permanente el dispositivo, revocará sus credenciales de telemetría y desvinculará sus asignaciones.
            </p>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem", marginTop: "0.5rem" }}>
              <Button type="button" variant="secondary" onClick={() => setIsDeleteModalOpen(false)} disabled={isDeleting}>
                Cancelar
              </Button>
              <Button
                type="button"
                variant="primary"
                onClick={handleDeleteDevice}
                isLoading={isDeleting}
                style={{ backgroundColor: "var(--status-critical)", borderColor: "var(--status-critical)" }}
              >
                Eliminar Permanentemente
              </Button>
            </div>
          </div>
        </Modal>
      )}

      {/* Tabs */}
      <Tabs
        activeTab={activeTab}
        onChange={setActiveTab}
        tabs={[
          { id: "telemetry", label: "Telemetría en Vivo", icon: <Activity size={16} /> },
          { id: "screen", label: "Demo de pantalla", icon: <Monitor size={16} /> },
          { id: "terminal", label: "Demo de diagnóstico", icon: <Terminal size={16} /> },
          { id: "inventory", label: "Inventario de Hardware & Software", icon: <Cpu size={16} /> },
          { id: "services", label: "Servicios del Sistema", icon: <Settings size={16} /> },
          { id: "assignment", label: "Asignación de Usuario", icon: <UserCheck size={16} /> },
        ]}
      />

      {/* Tab: Remote Screen */}
      {activeTab === "screen" && (
        <RemoteScreenViewer deviceId={device.id} hostname={device.hostname} isOnline={isOnline} />
      )}

      {/* Tab: Web Terminal */}
      {activeTab === "terminal" && (
        <WebTerminalView deviceId={device.id} hostname={device.hostname} isOnline={isOnline} />
      )}

      {/* Tab 1: Telemetry */}
      {activeTab === "telemetry" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
          <div className="grid-responsive" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(400px, 1fr))" }}>
            <Card header={<span style={{ fontWeight: 600, fontSize: "var(--text-sm)" }}>Uso de Procesador (CPU %)</span>}>
              <TelemetryChart title="CPU" samples={cpuSamples as any} unit="%" color="var(--brand-primary)" />
            </Card>

            <Card header={<span style={{ fontWeight: 600, fontSize: "var(--text-sm)" }}>Uso de Memoria RAM (%)</span>}>
              <TelemetryChart title="RAM" samples={memSamples as any} unit="%" color="var(--brand-secondary)" />
            </Card>

            <Card header={<span style={{ fontWeight: 600, fontSize: "var(--text-sm)" }}>Ocupación de Disco (%)</span>}>
              <TelemetryChart title="Disco" samples={diskSamples as any} unit="%" color="var(--status-warning)" />
            </Card>
          </div>
        </div>
      )}

      {/* Tab 2: Hardware & Software Inventory */}
      {activeTab === "inventory" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
          <Card header={<span style={{ fontWeight: 600, fontSize: "var(--text-sm)" }}>Especificaciones de Hardware</span>}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "1rem" }}>
              <div>
                <span style={{ fontSize: "var(--text-xs)", color: "var(--text-muted)" }}>Procesador</span>
                <div style={{ fontWeight: 600 }}>{hardware?.cpu_model || "Intel / AMD Core"}</div>
                <div style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)" }}>
                  {hardware?.physical_cores ? `${hardware.physical_cores} Núcleos físicos / ${hardware.logical_processors || hardware.physical_cores} lógicos` : "Monitoreado"}
                </div>
              </div>
              <div>
                <span style={{ fontSize: "var(--text-xs)", color: "var(--text-muted)" }}>Memoria RAM Total</span>
                <div style={{ fontWeight: 600, fontFamily: "var(--font-mono)" }}>
                  {hardware?.memory_bytes
                    ? `${(hardware.memory_bytes / (1024 ** 3)).toFixed(1)} GB`
                    : "16.0 GB"}
                </div>
              </div>
              <div>
                <span style={{ fontSize: "var(--text-xs)", color: "var(--text-muted)" }}>Último Inventariado</span>
                <div style={{ fontWeight: 600 }}>
                  {inventory?.collected_at ? new Date(inventory.collected_at).toLocaleString() : "Pendiente de reporte"}
                </div>
              </div>
            </div>
          </Card>

          <Card header={<span style={{ fontWeight: 600, fontSize: "var(--text-sm)" }}>Software Instalado & Paquetes</span>}>
            <Table
              columns={[
                { header: "Paquete / Aplicación", accessorKey: "name" },
                { header: "Versión", accessorKey: "version" },
                { header: "Editor / Publisher", accessorKey: "publisher" },
                { header: "Arquitectura", accessorKey: "architecture" },
              ]}
              data={inventory?.software_packages || []}
              keyExtractor={(s) => s.name}
              emptyMessage="No se ha inventariado software en este equipo aún."
            />
          </Card>
        </div>
      )}

      {/* Tab 3: System Services */}
      {activeTab === "services" && (
        <Card header={<span style={{ fontWeight: 600, fontSize: "var(--text-sm)" }}>Servicios del Sistema Monitoreados</span>}>
          <Table
            columns={[
              { header: "Nombre del Servicio", accessorKey: "name" },
              { header: "Nombre Visible", accessorKey: "display_name" },
              { header: "Estado", accessorKey: "status" },
              { header: "Tipo de Inicio", accessorKey: "start_type" },
            ]}
            data={inventory?.services || []}
            keyExtractor={(s) => s.name}
            emptyMessage="No se han detectado servicios registrados en este equipo."
          />
        </Card>
      )}

      {/* Tab 4: User Assignment */}
      {activeTab === "assignment" && (
        <Card header={<span style={{ fontWeight: 600, fontSize: "var(--text-sm)" }}>Vincular Equipo a Colaborador</span>}>
          <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem", maxWidth: "500px" }}>
            <p style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)" }}>
              Asigne este equipo a un usuario de la organización para delimitar tickets de soporte y permisos de autoservicio.
            </p>

            <Select
              label="Seleccionar Colaborador"
              value={selectedUserId}
              onChange={(e) => setSelectedUserId(e.target.value)}
              options={users.map((u) => ({
                value: u.id,
                label: `${u.full_name} (${u.email})`,
              }))}
            />

            <Button
              variant="primary"
              onClick={handleAssignUser}
              isLoading={isAssigning}
              disabled={!selectedUserId}
            >
              Confirmar Asignación
            </Button>
          </div>
        </Card>
      )}

      {/* Agent Token Modal */}
      <DeviceEnrollModal
        deviceId={device.id}
        deviceHostname={device.hostname}
        isOpen={isEnrollOpen}
        onClose={() => setIsEnrollOpen(false)}
      />
    </div>
  );
}
