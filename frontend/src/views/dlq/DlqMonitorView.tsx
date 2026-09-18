import React, { useEffect, useState, useCallback } from "react";
import { metricsApi } from "@/api/metrics";
import { devicesApi } from "@/api/devices";
import type { BatchStatusResponse, BatchDiagnosticsResponse } from "@/types/metrics";
import type { DeviceResponse } from "@/types/devices";
import { StatusIndicator } from "@/components/metrics/StatusIndicator";
import { Table } from "@/components/common/Table";
import { Button } from "@/components/common/Button";
import { Card } from "@/components/common/Card";
import { Modal } from "@/components/common/Modal";
import { Input } from "@/components/common/Input";
import { Select } from "@/components/common/Select";
import { useNotification } from "@/context/NotificationContext";
import { Database, RotateCw, RefreshCw, AlertTriangle, CheckSquare } from "lucide-react";

export function DlqMonitorView() {
  const { success, error: notifyError } = useNotification();
  const [devices, setDevices] = useState<DeviceResponse[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState<string>("");
  const [batchIdInput, setBatchIdInput] = useState("");
  const [queriedBatches, setQueriedBatches] = useState<BatchStatusResponse[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  // Diagnostics Modal state
  const [diagnosticsData, setDiagnosticsData] = useState<BatchDiagnosticsResponse | null>(null);

  // Decision Modal state
  const [decisionBatchId, setDecisionBatchId] = useState<string | null>(null);
  const [decisionType, setDecisionType] = useState<"PURGE_LOCAL" | "RETAIN">("PURGE_LOCAL");
  const [decisionReason, setDecisionReason] = useState("");
  const [isProcessingDecision, setIsProcessingDecision] = useState(false);

  const loadDevices = useCallback(async () => {
    try {
      const resp = await devicesApi.list({ limit: 100 });
      setDevices(resp.items);
      if (resp.items.length > 0 && !selectedDeviceId) {
        setSelectedDeviceId(resp.items[0]?.id || "");
      }
    } catch (err: any) {
      notifyError("Error al cargar dispositivos", err.message);
    }
  }, [notifyError, selectedDeviceId]);

  useEffect(() => {
    loadDevices();
  }, [loadDevices]);

  const handleQueryStatus = async () => {
    if (!selectedDeviceId) return;
    setIsLoading(true);
    try {
      const batchIds = batchIdInput
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);

      if (batchIds.length === 0) {
        setQueriedBatches([]);
        return;
      }

      const resp = await metricsApi.queryBatchStatuses(selectedDeviceId, batchIds);
      setQueriedBatches(resp.statuses);
    } catch (err: any) {
      notifyError("Error al consultar estado de lotes", err.message);
    } finally {
      setIsLoading(false);
    }
  };

  const handleFetchDiagnostics = async (batchId: string) => {
    if (!selectedDeviceId) return;
    try {
      const diag = await metricsApi.getDiagnostics(selectedDeviceId, batchId);
      setDiagnosticsData(diag);
    } catch (err: any) {
      notifyError("Error al obtener diagnóstico del lote", err.message);
    }
  };

  const handleRetry = async (batchId: string) => {
    if (!selectedDeviceId) return;
    try {
      await metricsApi.retryBatch(
        selectedDeviceId,
        batchId,
        "Reintento manual desde consola de operaciones"
      );
      success("Reintento programado para el lote", `Lote: ${batchId.substring(0, 8)}...`);
      await handleQueryStatus();
    } catch (err: any) {
      notifyError("Error al programar reintento", err.message);
    }
  };

  const handleDecisionSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedDeviceId || !decisionBatchId || !decisionReason.trim()) return;

    setIsProcessingDecision(true);
    try {
      await metricsApi.makeDecision(
        selectedDeviceId,
        decisionBatchId,
        decisionType,
        decisionReason.trim()
      );
      success("Decisión administrativa registrada", `Lote: ${decisionBatchId.substring(0, 8)}...`);
      setDecisionBatchId(null);
      setDecisionReason("");
      await handleQueryStatus();
    } catch (err: any) {
      notifyError("Error al registrar decisión", err.message);
    } finally {
      setIsProcessingDecision(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-6)" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "1rem" }}>
        <div>
          <h2 style={{ fontSize: "var(--text-xl)", fontWeight: 700 }}>Monitor de Dead-Letter Queue (DLQ)</h2>
          <p style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)", marginTop: "0.25rem" }}>
            Supervisión y recuperación de lotes de telemetría con errores de validación o agotamiento de reintentos
          </p>
        </div>
      </div>

      {/* Info Card */}
      <Card style={{ borderLeft: "4px solid var(--status-warning)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          <AlertTriangle size={24} color="var(--status-warning)" />
          <div style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)" }}>
            Los lotes que superan el número máximo de reintentos o presentan divergencias de digest se aíslan automáticamente en DLQ. Puede inspeccionar el diagnóstico sanitizado y emitir una decisión de depuración o retención local.
          </div>
        </div>
      </Card>

      {/* Query Bar */}
      <Card header={<span style={{ fontWeight: 600, fontSize: "var(--text-sm)" }}>Consultar Lotes por Dispositivo</span>}>
        <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr auto", gap: "1rem", alignItems: "flex-end" }}>
            <Select
              label="Dispositivo"
              value={selectedDeviceId}
              onChange={(e) => setSelectedDeviceId(e.target.value)}
              options={devices.map((d) => ({
                value: d.id,
                label: `${d.hostname} ${d.display_name ? `(${d.display_name})` : ""}`,
              }))}
            />

            <Input
              label="IDs de Lotes (separados por coma)"
              placeholder="UUID-1, UUID-2, ..."
              value={batchIdInput}
              onChange={(e) => setBatchIdInput(e.target.value)}
            />

            <Button
              variant="primary"
              onClick={handleQueryStatus}
              isLoading={isLoading}
              leftIcon={<RefreshCw size={14} />}
            >
              Consultar Estado
            </Button>
          </div>
        </div>
      </Card>

      {/* DLQ Batches Table */}
      <Card>
        <Table
          columns={[
            {
              header: "ID de Lote",
              cell: (b) => (
                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                  <Database size={16} color="var(--text-muted)" />
                  <span style={{ fontFamily: "var(--font-mono)", fontWeight: 600, color: "var(--text-primary)" }}>
                    {b.batch_id.substring(0, 8)}...
                  </span>
                </div>
              ),
              width: "140px",
            },
            {
              header: "Estado DLQ",
              cell: (b) => <StatusIndicator status={b.status} />,
              width: "160px",
            },
            {
              header: "Código de Error",
              cell: (b) => (
                <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--text-xs)", color: b.error_code ? "var(--status-critical)" : "var(--text-muted)" }}>
                  {b.error_code || "OK"}
                </span>
              ),
              width: "180px",
            },
            {
              header: "Reintentos / Reprocesos",
              cell: (b) => `${b.retry_count} / ${b.reprocess_count}`,
              width: "160px",
            },
            {
              header: "Decisión Operativa",
              cell: (b) => b.decision || "Sin decisión",
              width: "140px",
            },
            {
              header: "Acciones",
              align: "right",
              width: "200px",
              cell: (b) => (
                <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.375rem" }}>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleFetchDiagnostics(b.batch_id)}
                    style={{ padding: "4px 8px" }}
                  >
                    Diagnóstico
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => handleRetry(b.batch_id)}
                    leftIcon={<RotateCw size={12} />}
                    style={{ padding: "4px 8px" }}
                  >
                    Reintentar
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setDecisionBatchId(b.batch_id)}
                    leftIcon={<CheckSquare size={12} />}
                    style={{ padding: "4px 8px" }}
                  >
                    Decisión
                  </Button>
                </div>
              ),
            },
          ]}
          data={queriedBatches}
          keyExtractor={(b) => b.batch_id}
          emptyTitle="Sin consultas activas de DLQ"
          emptyMessage="Seleccione un equipo e ingrese identificadores de lote para verificar su trazabilidad en Dead-Letter Queue."
        />
      </Card>

      {/* Diagnostics Modal */}
      {diagnosticsData && (
        <Modal
          isOpen={Boolean(diagnosticsData)}
          onClose={() => setDiagnosticsData(null)}
          title="Diagnóstico Sanitizado de Lote"
          description={`Lote: ${diagnosticsData.batch_id}`}
        >
          <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
            <div>
              <span style={{ fontSize: "var(--text-xs)", color: "var(--text-muted)" }}>Digest SHA-256:</span>
              <pre
                style={{
                  marginTop: "0.25rem",
                  padding: "0.5rem",
                  backgroundColor: "var(--bg-input)",
                  borderRadius: "var(--radius-sm)",
                  fontFamily: "var(--font-mono)",
                  fontSize: "var(--text-xs)",
                  color: "var(--brand-primary)",
                }}
              >
                {diagnosticsData.payload_digest}
              </pre>
            </div>

            <div>
              <span style={{ fontSize: "var(--text-xs)", color: "var(--text-muted)" }}>Resumen Sanitizado:</span>
              <div
                style={{
                  marginTop: "0.25rem",
                  padding: "0.75rem",
                  backgroundColor: "var(--status-critical-bg)",
                  border: "1px solid var(--status-critical-border)",
                  borderRadius: "var(--radius-md)",
                  color: "var(--status-critical)",
                  fontSize: "var(--text-xs)",
                  fontFamily: "var(--font-mono)",
                }}
              >
                {diagnosticsData.error_summary || "Sin detalle de error registrado"}
              </div>
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: "0.5rem" }}>
              <Button variant="secondary" onClick={() => setDiagnosticsData(null)}>
                Cerrar
              </Button>
            </div>
          </div>
        </Modal>
      )}

      {/* Decision Modal */}
      {decisionBatchId && (
        <Modal
          isOpen={Boolean(decisionBatchId)}
          onClose={() => setDecisionBatchId(null)}
          title="Emitir Decisión Administrativa"
          description={`Lote: ${decisionBatchId}`}
        >
          <form onSubmit={handleDecisionSubmit} style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
            <Select
              label="Decisión Operativa"
              value={decisionType}
              onChange={(e) => setDecisionType(e.target.value as any)}
              options={[
                { value: "PURGE_LOCAL", label: "PURGE_LOCAL - Autorizar eliminación en cola local del agente" },
                { value: "RETAIN", label: "RETAIN - Conservar lote en agente para análisis forense" },
              ]}
            />

            <Input
              label="Justificación de Auditoría"
              placeholder="Indique el motivo técnico de la resolución..."
              value={decisionReason}
              onChange={(e) => setDecisionReason(e.target.value)}
              required
              autoFocus
            />

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem", marginTop: "1rem" }}>
              <Button type="button" variant="ghost" onClick={() => setDecisionBatchId(null)}>
                Cancelar
              </Button>
              <Button type="submit" variant="primary" isLoading={isProcessingDecision}>
                Confirmar Decisión
              </Button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}
