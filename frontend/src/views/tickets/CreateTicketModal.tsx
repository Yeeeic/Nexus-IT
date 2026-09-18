import { useState } from "react";
import { Modal } from "@/components/common/Modal";
import { Button } from "@/components/common/Button";
import { Input } from "@/components/common/Input";
import { Select } from "@/components/common/Select";
import { ticketsApi } from "@/api/tickets";
import type { TicketPriority, TicketResponse } from "@/types/tickets";
import { useNotification } from "@/context/NotificationContext";
import { Send } from "lucide-react";

export interface CreateTicketModalProps {
  isOpen: boolean;
  deviceId?: string | null | undefined;
  onClose: () => void;
  onCreated?: (ticket: TicketResponse) => void;
  onTicketCreated?: (ticket?: TicketResponse) => void;
}

export function CreateTicketModal({
  isOpen,
  deviceId,
  onClose,
  onCreated,
  onTicketCreated,
}: CreateTicketModalProps) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState<TicketPriority>("MEDIUM");
  const [category, setCategory] = useState("SOPORTE_GENERAL");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const { success, error: notifyError } = useNotification();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim() || !description.trim()) return;

    setIsSubmitting(true);
    try {
      const created = await ticketsApi.create({
        title: title.trim(),
        description: `[Categoría: ${category}]\n\n${description.trim()}`,
        priority,
        device_id: deviceId ?? null,
      });

      success(
        "Ticket Creado con Éxito",
        `Ticket #${created.ticket_number} asignado a la cola de soporte técnico.`
      );
      setTitle("");
      setDescription("");
      setPriority("MEDIUM");
      if (onCreated) onCreated(created);
      if (onTicketCreated) onTicketCreated(created);
      onClose();
    } catch (err: any) {
      notifyError("Error al registrar ticket de soporte", err.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="🎫 Crear Nuevo Ticket de Soporte Técnico"
      maxWidth="560px"
    >
      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
        <p style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)", lineHeight: 1.4 }}>
          Describe el problema o solicitud técnica que estás experimentando. Nuestro equipo de ingenieros recibirá la notificación de inmediato.
        </p>

        <Input
          label="Título del Incidente / Asunto"
          placeholder="Ej: Lentitud al abrir aplicaciones, error en VPN..."
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          required
        />

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
          <Select
            label="Categoría del Problema"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            options={[
              { value: "SOPORTE_GENERAL", label: "Soporte General" },
              { value: "HARDWARE", label: "Hardware & Rendimiento" },
              { value: "SOFTWARE", label: "Software & Aplicaciones" },
              { value: "RED_VPN", label: "Red, Conectividad & VPN" },
              { value: "SEGURIDAD", label: "Seguridad & Accesos" },
            ]}
          />

          <Select
            label="Nivel de Prioridad / Urgencia"
            value={priority}
            onChange={(e) => setPriority(e.target.value as TicketPriority)}
            options={[
              { value: "LOW", label: "Baja (Consulta / Mejora)" },
              { value: "MEDIUM", label: "Media (Afecta tarea puntual)" },
              { value: "HIGH", label: "Alta (Bloqueo parcial)" },
              { value: "CRITICAL", label: "Crítica (Equipo inoperativo)" },
            ]}
          />
        </div>

        <div>
          <label style={{ display: "block", fontSize: "var(--text-xs)", fontWeight: 500, color: "var(--text-secondary)", marginBottom: "0.375rem" }}>
            Descripción Detallada del Problema
          </label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Describe qué ocurrió, mensajes de error y pasos para reproducir..."
            rows={4}
            required
            style={{
              width: "100%",
              padding: "0.625rem 0.75rem",
              borderRadius: "var(--radius-md)",
              backgroundColor: "var(--bg-surface)",
              color: "var(--text-primary)",
              border: "1px solid var(--border-subtle)",
              fontSize: "var(--text-xs)",
              fontFamily: "inherit",
              resize: "vertical",
              outline: "none",
            }}
          />
        </div>

        <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem", marginTop: "0.5rem" }}>
          <Button type="button" variant="secondary" onClick={onClose} disabled={isSubmitting}>
            Cancelar
          </Button>
          <Button
            type="submit"
            variant="primary"
            isLoading={isSubmitting}
            leftIcon={<Send size={14} />}
          >
            Enviar Solicitud
          </Button>
        </div>
      </form>
    </Modal>
  );
}
