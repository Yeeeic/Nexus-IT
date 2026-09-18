import React from "react";
import { Card } from "../common/Card";

export interface MetricCardProps {
  title: string;
  value: string | number;
  unit?: string;
  delta?: {
    value: string;
    isPositive?: boolean;
    isGood?: boolean;
  };
  icon?: React.ReactNode;
  subtitle?: string;
  statusVariant?: "healthy" | "warning" | "critical" | "info";
}

export function MetricCard({
  title,
  value,
  unit,
  delta,
  icon,
  subtitle,
  statusVariant,
}: MetricCardProps) {
  const getBorderHighlight = () => {
    switch (statusVariant) {
      case "critical":
        return "1px solid var(--status-critical-border)";
      case "warning":
        return "1px solid var(--status-warning-border)";
      case "healthy":
        return "1px solid var(--status-healthy-border)";
      default:
        return "1px solid var(--border-subtle)";
    }
  };

  return (
    <Card
      style={{
        padding: "var(--space-4) var(--space-5)",
        border: getBorderHighlight(),
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "0.5rem" }}>
        <span style={{ fontSize: "var(--text-xs)", fontWeight: 500, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: "0.04em" }}>
          {title}
        </span>
        {icon && (
          <div
            style={{
              color: statusVariant
                ? `var(--status-${statusVariant})`
                : "var(--brand-primary)",
              display: "flex",
              alignItems: "center",
            }}
          >
            {icon}
          </div>
        )}
      </div>

      <div style={{ display: "flex", alignItems: "baseline", gap: "0.375rem" }}>
        <span style={{ fontSize: "var(--text-2xl)", fontWeight: 700, color: "var(--text-primary)", fontFamily: "var(--font-mono)" }}>
          {value}
        </span>
        {unit && (
          <span style={{ fontSize: "var(--text-xs)", fontWeight: 500, color: "var(--text-muted)" }}>
            {unit}
          </span>
        )}
      </div>

      {(delta || subtitle) && (
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginTop: "0.5rem", fontSize: "var(--text-xs)" }}>
          {delta && (
            <span
              style={{
                fontWeight: 600,
                color: delta.isGood
                  ? "var(--status-healthy)"
                  : delta.isGood === false
                  ? "var(--status-critical)"
                  : "var(--text-secondary)",
              }}
            >
              {delta.isPositive ? "+" : ""}
              {delta.value}
            </span>
          )}
          {subtitle && (
            <span style={{ color: "var(--text-muted)" }}>{subtitle}</span>
          )}
        </div>
      )}
    </Card>
  );
}
