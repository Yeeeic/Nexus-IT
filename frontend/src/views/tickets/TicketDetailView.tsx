import React, { useEffect, useState, useCallback, useRef } from "react";
import { ticketsApi } from "@/api/tickets";
import type { TicketResponse, CommentResponse, TicketStatus } from "@/types/tickets";
import { StatusIndicator } from "@/components/metrics/StatusIndicator";
import { Badge } from "@/components/common/Badge";
import { Button } from "@/components/common/Button";
import { Card } from "@/components/common/Card";
import { Skeleton } from "@/components/common/Skeleton";
import { useNotification } from "@/context/NotificationContext";
import {
  ArrowLeft,
  MessageSquare,
  Paperclip,
  Send,
  Lock,
  User,
  Clock,
  CheckCircle,
} from "lucide-react";

export interface TicketDetailViewProps {
  ticketId: string;
  onBack: () => void;
}

export function TicketDetailView({ ticketId, onBack }: TicketDetailViewProps) {
  const { success, error: notifyError } = useNotification();
  const [ticket, setTicket] = useState<TicketResponse | null>(null);
  const [comments, setComments] = useState<CommentResponse[]>([]);
  const [newComment, setNewComment] = useState("");
  const [isInternal, setIsInternal] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isSending, setIsSending] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const loadTicket = useCallback(async () => {
    setIsLoading(true);
    try {
      const [tck, cmts] = await Promise.all([
        ticketsApi.getById(ticketId),
        ticketsApi.listComments(ticketId).catch(() => ({ items: [] })),
      ]);
      setTicket(tck);
      setComments(cmts.items);
    } catch (err: any) {
      notifyError("Error al cargar ticket de soporte", err.message);
    } finally {
      setIsLoading(false);
    }
  }, [ticketId, notifyError]);

  useEffect(() => {
    loadTicket();
  }, [loadTicket]);

  const handleTransition = async (targetStatus: TicketStatus) => {
    if (!ticket) return;
    try {
      await ticketsApi.transition(ticketId, {
        expected_status: ticket.status,
        status: targetStatus,
      });
      success("Estado del ticket actualizado", `Nuevo estado: ${targetStatus}`);
      await loadTicket();
    } catch (err: any) {
      notifyError("Error al cambiar estado", err.message);
    }
  };

  const handleAddComment = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newComment.trim()) return;

    setIsSending(true);
    try {
      const added = await ticketsApi.addComment(ticketId, {
        content: newComment.trim(),
        is_internal: isInternal,
      });
      setComments((prev) => [...prev, added]);
      setNewComment("");
      success("Comentario agregado");
    } catch (err: any) {
      notifyError("Error al enviar comentario", err.message);
    } finally {
      setIsSending(false);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsUploading(true);
    try {
      await ticketsApi.uploadAttachment(ticketId, file);
      success("Archivo adjunto cargado exitosamente", file.name);
      await loadTicket();
    } catch (err: any) {
      notifyError("Error al subir archivo adjunto", err.message);
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  if (isLoading && !ticket) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
        <Skeleton height="60px" />
        <Skeleton height="200px" />
        <Skeleton height="150px" />
      </div>
    );
  }

  if (!ticket) {
    return (
      <div style={{ textAlign: "center", padding: "3rem" }}>
        <p>No se encontró el ticket especificado.</p>
        <Button variant="secondary" onClick={onBack} style={{ marginTop: "1rem" }}>
          Volver a la lista
        </Button>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-6)" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", flexWrap: "wrap", gap: "1rem" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          <Button variant="ghost" size="sm" onClick={onBack} leftIcon={<ArrowLeft size={16} />}>
            Volver
          </Button>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <span style={{ fontSize: "var(--text-lg)", fontFamily: "var(--font-mono)", fontWeight: 700, color: "var(--brand-primary)" }}>
                {ticket.ticket_number}
              </span>
              <h2 style={{ fontSize: "var(--text-xl)", fontWeight: 700 }}>{ticket.title}</h2>
              <StatusIndicator status={ticket.status} />
            </div>
            <div style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)", marginTop: "0.25rem", display: "flex", gap: "1rem" }}>
              <span>Solicitante ID: <strong style={{ fontFamily: "var(--font-mono)", color: "var(--text-primary)" }}>{ticket.created_by.substring(0, 8)}...</strong></span>
              <span>Asignado a: <strong style={{ color: "var(--text-primary)" }}>{ticket.assigned_to ? `${ticket.assigned_to.substring(0, 8)}...` : "Sin asignar"}</strong></span>
              <span>Fecha: <strong style={{ color: "var(--text-primary)" }}>{new Date(ticket.created_at).toLocaleString()}</strong></span>
            </div>
          </div>
        </div>

        {/* Status Transition Actions */}
        <div style={{ display: "flex", gap: "0.5rem" }}>
          {ticket.status === "OPEN" && (
            <Button
              variant="primary"
              size="sm"
              onClick={() => handleTransition("IN_PROGRESS")}
            >
              Tomar en Atención
            </Button>
          )}
          {ticket.status === "IN_PROGRESS" && (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => handleTransition("RESOLVED")}
              leftIcon={<CheckCircle size={14} />}
            >
              Marcar como Resuelto
            </Button>
          )}
          {ticket.status === "RESOLVED" && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => handleTransition("CLOSED")}
            >
              Cerrar Ticket
            </Button>
          )}
        </div>
      </div>

      {/* Description Card */}
      <Card
        header={
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%" }}>
            <span style={{ fontWeight: 600, fontSize: "var(--text-sm)" }}>Descripción del Requerimiento</span>
            <Badge
              variant={
                ticket.priority === "CRITICAL"
                  ? "critical"
                  : ticket.priority === "HIGH"
                  ? "warning"
                  : "info"
              }
            >
              Prioridad {ticket.priority}
            </Badge>
          </div>
        }
      >
        <p style={{ whiteSpace: "pre-wrap", color: "var(--text-primary)", lineHeight: 1.6 }}>
          {ticket.description}
        </p>
      </Card>

      {/* Conversation Thread */}
      <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
        <h3 style={{ fontSize: "var(--text-base)", fontWeight: 600, display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <MessageSquare size={18} color="var(--brand-primary)" />
          <span>Historial de Respuestas y Notas Internas ({comments.length})</span>
        </h3>

        {comments.length === 0 ? (
          <div
            style={{
              padding: "2rem",
              textAlign: "center",
              backgroundColor: "var(--bg-surface)",
              border: "1px dashed var(--border-subtle)",
              borderRadius: "var(--radius-lg)",
              color: "var(--text-muted)",
              fontSize: "var(--text-xs)",
            }}
          >
            No hay comentarios registrados en este ticket aún.
          </div>
        ) : (
          comments.map((cmt) => (
            <div
              key={cmt.id}
              className="nexus-card"
              style={{
                borderLeft: cmt.is_internal
                  ? "4px solid var(--status-warning)"
                  : "4px solid var(--brand-primary)",
                backgroundColor: cmt.is_internal
                  ? "var(--status-warning-bg)"
                  : "var(--bg-surface)",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "0.5rem" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                  <User size={14} color="var(--text-secondary)" />
                  <span style={{ fontWeight: 600, fontSize: "var(--text-xs)", color: "var(--text-primary)", fontFamily: "var(--font-mono)" }}>
                    Usuario: {cmt.user_id.substring(0, 8)}...
                  </span>
                  {cmt.is_internal && (
                    <Badge variant="warning" style={{ fontSize: "var(--text-2xs)", padding: "1px 6px" }}>
                      <Lock size={10} style={{ marginRight: "3px" }} /> Nota Interna
                    </Badge>
                  )}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: "0.25rem", fontSize: "var(--text-2xs)", color: "var(--text-muted)" }}>
                  <Clock size={12} />
                  <span>{new Date(cmt.created_at).toLocaleString()}</span>
                </div>
              </div>
              <p style={{ whiteSpace: "pre-wrap", fontSize: "var(--text-sm)", color: "var(--text-primary)" }}>
                {cmt.content}
              </p>
            </div>
          ))
        )}

        {/* Comment Form */}
        <Card>
          <form onSubmit={handleAddComment} style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
            <textarea
              rows={3}
              placeholder="Escriba su respuesta o nota de diagnóstico..."
              value={newComment}
              onChange={(e) => setNewComment(e.target.value)}
              style={{
                width: "100%",
                padding: "0.75rem",
                backgroundColor: "var(--bg-input)",
                color: "var(--text-primary)",
                border: "1px solid var(--border-default)",
                borderRadius: "var(--radius-md)",
                fontSize: "var(--text-sm)",
                fontFamily: "var(--font-sans)",
                outline: "none",
                resize: "vertical",
              }}
            />

            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "0.5rem" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
                <label style={{ display: "flex", alignItems: "center", gap: "0.375rem", fontSize: "var(--text-xs)", cursor: "pointer", color: "var(--text-secondary)" }}>
                  <input
                    type="checkbox"
                    checked={isInternal}
                    onChange={(e) => setIsInternal(e.target.checked)}
                  />
                  <span>Nota interna (no visible para el cliente)</span>
                </label>

                {/* Hidden File Input */}
                <input
                  type="file"
                  ref={fileInputRef}
                  onChange={handleFileUpload}
                  style={{ display: "none" }}
                  accept=".pdf,.png,.jpg,.jpeg,.log,.txt"
                />

                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => fileInputRef.current?.click()}
                  isLoading={isUploading}
                  leftIcon={<Paperclip size={14} />}
                >
                  Adjuntar Archivo
                </Button>
              </div>

              <Button
                type="submit"
                variant="primary"
                size="sm"
                isLoading={isSending}
                disabled={!newComment.trim()}
                leftIcon={<Send size={14} />}
              >
                Enviar Respuesta
              </Button>
            </div>
          </form>
        </Card>
      </div>
    </div>
  );
}
