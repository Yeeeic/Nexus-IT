import { useEffect, useState, useCallback } from "react";
import { ticketsApi } from "@/api/tickets";
import type { TicketResponse } from "@/types/tickets";
import { StatusIndicator } from "@/components/metrics/StatusIndicator";
import { Badge } from "@/components/common/Badge";
import { Table } from "@/components/common/Table";
import { Button } from "@/components/common/Button";
import { Input } from "@/components/common/Input";
import { Select } from "@/components/common/Select";
import { Modal } from "@/components/common/Modal";
import { CreateTicketModal } from "./CreateTicketModal";
import { TicketDetailView } from "./TicketDetailView";
import { useNotification } from "@/context/NotificationContext";
import { Plus, Search, RefreshCw, Eye, Trash2, AlertTriangle } from "lucide-react";

export function TicketsListView() {
  const { success, error: notifyError } = useNotification();
  const [tickets, setTickets] = useState<TicketResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [priorityFilter, setPriorityFilter] = useState("ALL");
  const [selectedTicketId, setSelectedTicketId] = useState<string | null>(null);
  const [isCreateOpen, setIsCreateOpen] = useState(false);

  // Delete state
  const [deleteTarget, setDeleteTarget] = useState<TicketResponse | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  const loadTickets = useCallback(async () => {
    setIsLoading(true);
    try {
      const response = await ticketsApi.list({ limit: 100 });
      setTickets(response.items);
    } catch (err: any) {
      notifyError("Error al cargar tickets de soporte", err.message);
    } finally {
      setIsLoading(false);
    }
  }, [notifyError]);

  useEffect(() => {
    loadTickets();
  }, [loadTickets]);

  const handleDeleteTicket = async () => {
    if (!deleteTarget) return;
    const targetId = deleteTarget.id;
    const targetNumber = deleteTarget.ticket_number;
    setIsDeleting(true);
    try {
      await ticketsApi.delete(targetId);
      setTickets((prev) => prev.filter((t) => t.id !== targetId));
      setDeleteTarget(null);
      success("Ticket eliminado", `El ticket #${targetNumber} fue eliminado.`);
      await loadTickets();
    } catch (err: any) {
      notifyError("Error al eliminar ticket", err.message);
    } finally {
      setIsDeleting(false);
    }
  };

  if (selectedTicketId) {
    return (
      <TicketDetailView
        ticketId={selectedTicketId}
        onBack={() => setSelectedTicketId(null)}
      />
    );
  }

  // Filtered tickets
  const filtered = tickets.filter((t) => {
    const matchesSearch =
      t.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      t.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
      t.ticket_number.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesStatus = statusFilter === "ALL" || t.status === statusFilter;
    const matchesPriority = priorityFilter === "ALL" || t.priority === priorityFilter;
    return matchesSearch && matchesStatus && matchesPriority;
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-6)" }}>
      {/* Header & Actions */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "1rem" }}>
        <div>
          <h2 style={{ fontSize: "var(--text-xl)", fontWeight: 700 }}>Mesa de Ayuda & Soporte Técnico</h2>
          <p style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)", marginTop: "0.25rem" }}>
            Gestión de incidentes, solicitudes de servicio y soporte a usuarios ({filtered.length} tickets)
          </p>
        </div>

        <div style={{ display: "flex", gap: "0.75rem" }}>
          <Button
            variant="secondary"
            size="sm"
            onClick={loadTickets}
            isLoading={isLoading}
            leftIcon={<RefreshCw size={14} />}
          >
            Actualizar
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => setIsCreateOpen(true)}
            leftIcon={<Plus size={16} />}
          >
            Nuevo Ticket
          </Button>
        </div>
      </div>

      {/* Filters Toolbar */}
      <div
        style={{
          display: "flex",
          gap: "1rem",
          alignItems: "center",
          flexWrap: "wrap",
          padding: "1rem",
          backgroundColor: "var(--bg-surface)",
          border: "1px solid var(--border-subtle)",
          borderRadius: "var(--radius-lg)",
        }}
      >
        <div style={{ flex: 1, minWidth: "220px" }}>
          <Input
            placeholder="Buscar por número, título o descripción..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            leftIcon={<Search size={16} />}
          />
        </div>

        <div style={{ width: "160px" }}>
          <Select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            options={[
              { value: "ALL", label: "Todos los estados" },
              { value: "NEW", label: "Nuevo (NEW)" },
              { value: "ASSIGNED", label: "Asignado" },
              { value: "IN_PROGRESS", label: "En progreso" },
              { value: "PENDING_CUSTOMER", label: "Pendiente" },
              { value: "RESOLVED", label: "Resuelto" },
              { value: "CLOSED", label: "Cerrado" },
            ]}
            style={{ height: "36px" }}
          />
        </div>

        <div style={{ width: "160px" }}>
          <Select
            value={priorityFilter}
            onChange={(e) => setPriorityFilter(e.target.value)}
            options={[
              { value: "ALL", label: "Todas las prioridades" },
              { value: "CRITICAL", label: "Crítica" },
              { value: "HIGH", label: "Alta" },
              { value: "MEDIUM", label: "Media" },
              { value: "LOW", label: "Baja" },
            ]}
            style={{ height: "36px" }}
          />
        </div>
      </div>

      {/* Tickets Table */}
      <Table
        columns={[
          {
            header: "Ticket #",
            cell: (t) => (
              <span style={{ fontFamily: "var(--font-mono)", fontWeight: 700, color: "var(--brand-primary)" }}>
                {t.ticket_number}
              </span>
            ),
            width: "140px",
          },
          {
            header: "Título",
            cell: (t) => (
              <div style={{ display: "flex", flexDirection: "column" }}>
                <span style={{ fontWeight: 600, color: "var(--text-primary)" }}>{t.title}</span>
                <span style={{ fontSize: "var(--text-2xs)", color: "var(--text-muted)" }}>
                  {t.description ? (t.description.length > 70 ? `${t.description.substring(0, 70)}...` : t.description) : "Sin descripción"}
                </span>
              </div>
            ),
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
            width: "110px",
          },
          {
            header: "Fecha",
            cell: (t) => new Date(t.created_at).toLocaleDateString(),
            width: "110px",
          },
          {
            header: "Acciones",
            align: "right",
            width: "120px",
            cell: (t) => (
              <div style={{ display: "flex", gap: "0.4rem", justifyContent: "flex-end" }}>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setSelectedTicketId(t.id)}
                  leftIcon={<Eye size={14} />}
                  style={{ padding: "4px 8px" }}
                  title="Ver detalle del ticket"
                >
                  Ver
                </Button>
                <Button
                  variant="danger"
                  size="sm"
                  onClick={(e) => {
                    e.stopPropagation();
                    setDeleteTarget(t);
                  }}
                  leftIcon={<Trash2 size={14} />}
                  style={{ padding: "4px 8px" }}
                  title="Eliminar ticket"
                />
              </div>
            ),
          },
        ]}
        data={filtered}
        keyExtractor={(t) => t.id}
        onRowClick={(t) => setSelectedTicketId(t.id)}
        emptyTitle="Sin tickets de soporte"
        emptyMessage="No hay tickets de soporte registrados que coincidan con los filtros."
      />

      {/* Ticket Creation Modal */}
      <CreateTicketModal
        isOpen={isCreateOpen}
        onClose={() => setIsCreateOpen(false)}
        onTicketCreated={loadTickets}
      />

      {/* Delete Confirmation Modal */}
      {deleteTarget && (
        <Modal
          isOpen={true}
          onClose={() => setDeleteTarget(null)}
          title="Confirmar Eliminación de Ticket"
        >
          <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", color: "var(--status-critical)" }}>
              <AlertTriangle size={24} />
              <div style={{ fontWeight: 600 }}>¿Deseas eliminar este ticket de soporte?</div>
            </div>
            <p style={{ fontSize: "var(--text-sm)", color: "var(--text-secondary)" }}>
              Estás a punto de eliminar el ticket <strong>#{deleteTarget.ticket_number}</strong> (<em>"{deleteTarget.title}"</em>).
              Esta acción es irreversible y eliminará los comentarios y adjuntos vinculados.
            </p>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.75rem", marginTop: "1rem" }}>
              <Button
                variant="secondary"
                onClick={() => setDeleteTarget(null)}
                disabled={isDeleting}
              >
                Cancelar
              </Button>
              <Button
                variant="danger"
                onClick={handleDeleteTicket}
                isLoading={isDeleting}
                leftIcon={<Trash2 size={16} />}
              >
                Eliminar Ticket
              </Button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
