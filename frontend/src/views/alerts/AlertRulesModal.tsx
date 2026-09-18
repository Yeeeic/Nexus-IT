import React, { useState } from "react";
import { metricsApi } from "@/api/metrics";
import { Modal } from "@/components/common/Modal";
import { Button } from "@/components/common/Button";
import { Input } from "@/components/common/Input";
import { Select } from "@/components/common/Select";
import { useNotification } from "@/context/NotificationContext";
import type { AlertRuleInput, AlertSeverity, ComparisonOperator } from "@/types/metrics";

export interface AlertRulesModalProps {
  isOpen: boolean;
  onClose: () => void;
  onRuleCreated: () => void;
}

export function AlertRulesModal({ isOpen, onClose, onRuleCreated }: AlertRulesModalProps) {
  const { success, error: notifyError } = useNotification();
  const [name, setName] = useState("");
  const [metricName, setMetricName] = useState("system.cpu.usage");
  const [operator, setOperator] = useState<ComparisonOperator>("GT");
  const [thresholdValue, setThresholdValue] = useState<number>(90);
  const [durationSeconds, setDurationSeconds] = useState<number>(120);
  const [severity, setSeverity] = useState<AlertSeverity>("CRITICAL");
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;

    setIsLoading(true);
    try {
      const input: AlertRuleInput = {
        name: name.trim(),
        metric_name: metricName,
        operator,
        threshold_value: Number(thresholdValue),
        duration_seconds: Number(durationSeconds),
        severity,
      };

      await metricsApi.createAlertRule(input);
      success("Regla de alerta creada exitosamente", `Regla: ${name}`);
      onRuleCreated();
      onClose();
    } catch (err: any) {
      notifyError("Error al crear la regla de alerta", err.message);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Crear Nueva Regla de Alerta"
      description="Configure umbrales de monitoreo proactivo con ventanas de persistencia"
    >
      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
        <Input
          label="Nombre de la Regla"
          placeholder="CPU Saturado > 90% (2 min)"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          autoFocus
        />

        <Select
          label="Métrica Monitoreada"
          value={metricName}
          onChange={(e) => setMetricName(e.target.value)}
          options={[
            { value: "system.cpu.usage", label: "Uso de Procesador (system.cpu.usage %)" },
            { value: "system.memory.usage", label: "Ocupación de Memoria RAM (system.memory.usage %)" },
            { value: "system.disk.usage", label: "Ocupación de Disco (system.disk.usage %)" },
            { value: "system.network.errors", label: "Errores de Red (system.network.errors)" },
          ]}
        />

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
          <Select
            label="Operador de Comparación"
            value={operator}
            onChange={(e) => setOperator(e.target.value as ComparisonOperator)}
            options={[
              { value: "GT", label: "Mayor que (>)" },
              { value: "GTE", label: "Mayor o igual que (>=)" },
              { value: "LT", label: "Menor que (<)" },
              { value: "LTE", label: "Menor o igual que (<=)" },
              { value: "EQ", label: "Igual a (=)" },
            ]}
          />

          <Input
            label="Valor Umbral"
            type="number"
            value={thresholdValue}
            onChange={(e) => setThresholdValue(Number(e.target.value))}
            required
          />
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
          <Input
            label="Ventana de Persistencia (segundos)"
            type="number"
            value={durationSeconds}
            onChange={(e) => setDurationSeconds(Number(e.target.value))}
            helperText="Previene falsos positivos por picos transitorios (flapping)"
            required
          />

          <Select
            label="Nivel de Severidad"
            value={severity}
            onChange={(e) => setSeverity(e.target.value as AlertSeverity)}
            options={[
              { value: "CRITICAL", label: "Crítico (Alerta Inmediata)" },
              { value: "WARNING", label: "Advertencia" },
              { value: "INFO", label: "Informativo" },
            ]}
          />
        </div>

        <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem", marginTop: "1rem" }}>
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button type="submit" variant="primary" isLoading={isLoading}>
            Guardar Regla
          </Button>
        </div>
      </form>
    </Modal>
  );
}
