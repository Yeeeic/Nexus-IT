import { useEffect, useState, useCallback } from "react";
import { devicesApi } from "@/api/devices";
import type { DeviceResponse, DeviceEnrollmentRequest, DeviceEnrollmentResponse } from "@/types/devices";
import { StatusIndicator } from "@/components/metrics/StatusIndicator";
import { Table } from "@/components/common/Table";
import { Button } from "@/components/common/Button";
import { Input } from "@/components/common/Input";
import { Select } from "@/components/common/Select";
import { Modal } from "@/components/common/Modal";
import { DeviceEnrollModal } from "./DeviceEnrollModal";
import { DeviceDetailView } from "./DeviceDetailView";
import { QuickInstallerModal } from "./QuickInstallerModal";
import { useNotification } from "@/context/NotificationContext";
import { getDeviceStatus } from "@/utils/deviceStatus";
import { Plus, Search, Key, RefreshCw, Eye, Zap, Trash2, AlertTriangle } from "lucide-react";

export function DevicesListView() {
  const { success, error: notifyError } = useNotification();
  const [devices, setDevices] = useState<DeviceResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [selectedDeviceId, setSelectedDeviceId] = useState<string | null>(null);

  // Quick Installer modal state
  const [isQuickInstallOpen, setIsQuickInstallOpen] = useState(false);

  // Creation Modal state
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [newHostname, setNewHostname] = useState("");
  const [newDisplayName, setNewDisplayName] = useState("");
  const [isCreating, setIsCreating] = useState(false);

  // Enroll Token Modal state
  const [enrollTarget, setEnrollTarget] = useState<DeviceResponse | null>(null);
  const [createdEnrollment, setCreatedEnrollment] = useState<DeviceEnrollmentResponse | null>(null);

  // Delete Device state
  const [deleteDeviceTarget, setDeleteDeviceTarget] = useState<DeviceResponse | null>(null);
  const [isDeletingDevice, setIsDeletingDevice] = useState(false);

  const loadDevices = useCallback(async () => {
    setIsLoading(true);
    try {
      const response = await devicesApi.list({ limit: 100 });
      setDevices(response.items);
    } catch (err: any) {
      notifyError("Error al cargar la lista de dispositivos", err.message);
    } finally {
      setIsLoading(false);
    }
  }, [notifyError]);

  useEffect(() => {
    loadDevices();
    const interval = setInterval(() => {
      if (typeof document !== "undefined" && document.visibilityState === "visible") {
        loadDevices();
      }
    }, 10000); // 10s polling for live online/offline state
    return () => clearInterval(interval);
  }, [loadDevices]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newHostname.trim()) return;

    setIsCreating(true);
    try {
      const input: DeviceEnrollmentRequest = {
        hostname: newHostname.trim(),
        display_name: newDisplayName.trim() || undefined,
      };
      const created = await devicesApi.create(input);
      success("Dispositivo registrado exitosamente", `Equipo: ${created.hostname}`);
      setIsCreateOpen(false);
      setNewHostname("");
      setNewDisplayName("");
      await loadDevices();
      setCreatedEnrollment(created);
      setEnrollTarget(created);
    } catch (err: any) {
      notifyError("Error al registrar dispositivo", err.message);
    } finally {
      setIsCreating(false);
    }
  };

  const handleDeleteDevice = async () => {
    if (!deleteDeviceTarget) return;
    const targetId = deleteDeviceTarget.id;
    const targetHostname = deleteDeviceTarget.hostname;
    setIsDeletingDevice(true);
    try {
      await devicesApi.delete(targetId);
      setDevices((prev) => prev.filter((d) => d.id !== targetId));
      setDeleteDeviceTarget(null);
      success("Dispositivo Desaprovisionado", `El equipo ${targetHostname} fue eliminado de la flota.`);
      await loadDevices();
    } catch (err: any) {
      notifyError("Error al eliminar dispositivo", err.message);
    } finally {
      setIsDeletingDevice(false);
    }
  };

  if (selectedDeviceId) {
    return (
      <DeviceDetailView
        deviceId={selectedDeviceId}
        onBack={() => {
          setSelectedDeviceId(null);
          loadDevices();
        }}
      />
    );
  }

  // Filtered devices (active only)
  const filtered = devices.filter((d) => {
    if (d.is_active === false) return false;
    const matchesSearch =
      d.hostname.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (d.display_name && d.display_name.toLowerCase().includes(searchQuery.toLowerCase())) ||
      d.id.includes(searchQuery);
    const status = getDeviceStatus(d);
    const matchesStatus = statusFilter === "ALL" || status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-6)" }}>
      {/* Header & Actions */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "1rem" }}>
        <div>
          <h2 style={{ fontSize: "var(--text-xl)", fontWeight: 700 }}>Inventario de Dispositivos</h2>
          <p style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)", marginTop: "0.25rem" }}>
            Supervisión continua, hardware, software, servicios y aprovisionamiento seguro de agentes
          </p>
        </div>

        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <Button
            variant="secondary"
            size="sm"
            onClick={loadDevices}
            isLoading={isLoading}
            leftIcon={<RefreshCw size={14} />}
          >
            Actualizar
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setIsQuickInstallOpen(true)}
            leftIcon={<Zap size={14} color="var(--brand-primary)" />}
          >
            🚀 Conectar Dispositivo (1-Clic)
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => setIsCreateOpen(true)}
            leftIcon={<Plus size={14} />}
          >
            Registrar Manual
          </Button>
        </div>
      </div>

      {/* Filter Bar */}
      <div
        className="nexus-card"
        style={{
          padding: "var(--space-3) var(--space-4)",
          display: "flex",
          alignItems: "center",
          gap: "1rem",
          flexWrap: "wrap",
        }}
      >
        <div style={{ flex: 1, minWidth: "240px" }}>
          <Input
            placeholder="Buscar por nombre de host, etiqueta o identificador..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            leftIcon={<Search size={16} />}
            style={{ height: "36px" }}
          />
        </div>

        <div style={{ width: "200px" }}>
          <Select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            options={[
              { value: "ALL", label: "Todos los estados" },
              { value: "ONLINE", label: "En línea (Activos)" },
              { value: "OFFLINE", label: "Desconectados (Inactivos)" },
            ]}
            style={{ height: "36px" }}
          />
        </div>
      </div>

      {/* Devices Table */}
      <Table
        columns={[
          {
            header: "Nombre de Host",
            cell: (d) => (
              <div style={{ display: "flex", flexDirection: "column" }}>
                <span style={{ fontWeight: 600, color: "var(--text-primary)" }}>{d.hostname}</span>
                {d.display_name && (
                  <span style={{ fontSize: "var(--text-xs)", color: "var(--brand-primary)" }}>
                    {d.display_name}
                  </span>
                )}
                <span style={{ fontSize: "var(--text-2xs)", color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
                  ID: {d.id.substring(0, 8)}...
                </span>
              </div>
            ),
          },
          {
            header: "Estado",
            cell: (d) => <StatusIndicator status={getDeviceStatus(d)} />,
            width: "140px",
          },
          {
            header: "Último Contacto",
            cell: (d) => (d.last_seen_at ? new Date(d.last_seen_at).toLocaleString() : "Nunca"),
            width: "180px",
          },
          {
            header: "Fecha de Registro",
            cell: (d) => new Date(d.created_at).toLocaleDateString(),
            width: "140px",
          },
          {
            header: "Acciones",
            align: "right",
            width: "220px",
            cell: (d) => (
              <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.375rem" }}>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={(e) => {
                    e.stopPropagation();
                    setCreatedEnrollment(null);
                    setEnrollTarget(d);
                  }}
                  leftIcon={<Key size={14} />}
                  title="Generar nuevo token de agente"
                  style={{ padding: "4px 8px" }}
                >
                  Token
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setSelectedDeviceId(d.id)}
                  leftIcon={<Eye size={14} />}
                  style={{ padding: "4px 8px" }}
                >
                  Detalle
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={(e) => {
                    e.stopPropagation();
                    setDeleteDeviceTarget(d);
                  }}
                  title="Desaprovisionar y eliminar dispositivo de la flota"
                  style={{ padding: "4px 8px", color: "var(--status-critical)" }}
                >
                  <Trash2 size={14} />
                </Button>
              </div>
            ),
          },
        ]}
        data={filtered}
        keyExtractor={(d) => d.id}
        onRowClick={(d) => setSelectedDeviceId(d.id)}
        emptyTitle="Sin dispositivos encontrados"
        emptyMessage="No hay dispositivos registrados que coincidan con los filtros seleccionados."
      />

      {/* Delete Device Confirmation Modal */}
      {deleteDeviceTarget && (
        <Modal
          isOpen={Boolean(deleteDeviceTarget)}
          onClose={() => setDeleteDeviceTarget(null)}
          title="⚠️ Confirmar Desaprovisionamiento de Dispositivo"
          maxWidth="460px"
        >
          <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", color: "var(--status-critical)" }}>
              <AlertTriangle size={24} />
              <div style={{ fontWeight: 600, fontSize: "var(--text-sm)" }}>
                ¿Desaprovisionar el equipo {deleteDeviceTarget.hostname}?
              </div>
            </div>
            <p style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)", lineHeight: 1.4 }}>
              Esta acción revocará inmediatamente todos los tokens del agente, borrará su inventario de hardware y eliminará el registro de la flota de monitoreo.
            </p>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem", marginTop: "0.5rem" }}>
              <Button type="button" variant="secondary" onClick={() => setDeleteDeviceTarget(null)} disabled={isDeletingDevice}>
                Cancelar
              </Button>
              <Button
                type="button"
                variant="primary"
                onClick={handleDeleteDevice}
                isLoading={isDeletingDevice}
                style={{ backgroundColor: "var(--status-critical)", borderColor: "var(--status-critical)" }}
              >
                Eliminar Dispositivo
              </Button>
            </div>
          </div>
        </Modal>
      )}

      {/* Device Registration Modal */}
      <Modal
        isOpen={isCreateOpen}
        onClose={() => setIsCreateOpen(false)}
        title="Registrar Nuevo Dispositivo"
        description="Aprovisione un equipo para habilitar telemetría y generar token de agente inicial"
      >
        <form onSubmit={handleCreate} style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          <Input
            label="Nombre de Host (Hostname)"
            placeholder="srv-prod-db-01"
            value={newHostname}
            onChange={(e) => setNewHostname(e.target.value)}
            required
            autoFocus
          />

          <Input
            label="Nombre Descriptivo / Etiqueta (Opcional)"
            placeholder="Base de datos primaria producción"
            value={newDisplayName}
            onChange={(e) => setNewDisplayName(e.target.value)}
          />

          <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem", marginTop: "1rem" }}>
            <Button type="button" variant="ghost" onClick={() => setIsCreateOpen(false)}>
              Cancelar
            </Button>
            <Button type="submit" variant="primary" isLoading={isCreating}>
              Guardar y Generar Token
            </Button>
          </div>
        </form>
      </Modal>

      {/* Agent Enrollment Modal */}
      {enrollTarget && (
        <DeviceEnrollModal
          deviceId={enrollTarget.id}
          deviceHostname={enrollTarget.hostname}
          initialToken={createdEnrollment?.token}
          isOpen={Boolean(enrollTarget)}
          onClose={() => {
            setEnrollTarget(null);
            setCreatedEnrollment(null);
          }}
        />
      )}

      {/* Quick 1-Click Installer Modal */}
      <QuickInstallerModal
        isOpen={isQuickInstallOpen}
        onClose={() => {
          setIsQuickInstallOpen(false);
          loadDevices();
        }}
      />
    </div>
  );
}
