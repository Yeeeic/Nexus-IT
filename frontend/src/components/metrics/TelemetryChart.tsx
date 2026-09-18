import { useState, useId } from "react";
import type { TelemetrySample } from "@/types/metrics";
import { Table } from "../common/Table";
import { Button } from "../common/Button";
import { Table as TableIcon, Activity } from "lucide-react";

export interface TelemetryChartProps {
  title: string;
  samples: TelemetrySample[];
  unit?: string;
  color?: string;
  height?: number;
}

export function TelemetryChart({
  title,
  samples,
  unit = "%",
  color = "var(--brand-primary)",
  height = 180,
}: TelemetryChartProps) {
  const [viewMode, setViewMode] = useState<"chart" | "table">("chart");
  const [hoveredSample, setHoveredSample] = useState<TelemetrySample | null>(null);
  const gradientId = useId();

  if (samples.length === 0) {
    return (
      <div
        style={{
          height: `${height}px`,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--text-muted)",
          fontSize: "var(--text-xs)",
          border: "1px dashed var(--border-subtle)",
          borderRadius: "var(--radius-md)",
        }}
      >
        Sin muestras de telemetría recientes
      </div>
    );
  }

  // Sort chronological
  const sorted = [...samples].sort(
    (a, b) => new Date(a.recorded_at).getTime() - new Date(b.recorded_at).getTime()
  );

  const values = sorted.map((s) => Number(s.metric_value));
  const minVal = Math.min(...values, 0);
  const maxVal = Math.max(...values, 100);
  const range = maxVal - minVal || 1;

  // SVG coordinates
  const svgWidth = 600;
  const svgHeight = height - 40;
  const padding = 20;

  const points = sorted.map((s, idx) => {
    const x = padding + (idx / (sorted.length - 1 || 1)) * (svgWidth - padding * 2);
    const normalizedY = (Number(s.metric_value) - minVal) / range;
    const y = svgHeight - padding - normalizedY * (svgHeight - padding * 2);
    return { x, y, sample: s };
  });

  const polylinePoints = points.map((p) => `${p.x},${p.y}`).join(" ");
  const areaPoints = `${padding},${svgHeight - padding} ${polylinePoints} ${
    svgWidth - padding
  },${svgHeight - padding}`;

  return (
    <div style={{ width: "100%", display: "flex", flexDirection: "column", gap: "0.5rem" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: "0.5rem" }}>
          <span style={{ fontSize: "var(--text-xs)", fontWeight: 600, color: "var(--text-secondary)", textTransform: "uppercase" }}>
            {title}
          </span>
          {hoveredSample ? (
            <span style={{ fontSize: "var(--text-xs)", color: "var(--brand-primary)", fontFamily: "var(--font-mono)", fontWeight: 600 }}>
              {Number(hoveredSample.metric_value).toFixed(1)} {unit} ({new Date(hoveredSample.recorded_at).toLocaleTimeString()})
            </span>
          ) : (
            <span style={{ fontSize: "var(--text-xs)", color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
              Último: {values[values.length - 1]?.toFixed(1)} {unit}
            </span>
          )}
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setViewMode((m) => (m === "chart" ? "table" : "chart"))}
          leftIcon={viewMode === "chart" ? <TableIcon size={14} /> : <Activity size={14} />}
          style={{ height: "24px", padding: "0 6px", fontSize: "var(--text-2xs)" }}
        >
          {viewMode === "chart" ? "Ver tabla" : "Ver gráfica"}
        </Button>
      </div>

      {viewMode === "chart" ? (
        <div style={{ width: "100%", height: `${height}px`, position: "relative" }}>
          <svg
            viewBox={`0 0 ${svgWidth} ${svgHeight}`}
            style={{ width: "100%", height: "100%", overflow: "visible" }}
          >
            <defs>
              <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={color} stopOpacity="0.3" />
                <stop offset="100%" stopColor={color} stopOpacity="0.0" />
              </linearGradient>
            </defs>

            {/* Background Grid */}
            <line
              x1={padding}
              y1={padding}
              x2={svgWidth - padding}
              y2={padding}
              stroke="var(--border-subtle)"
              strokeDasharray="4 4"
            />
            <line
              x1={padding}
              y1={svgHeight / 2}
              x2={svgWidth - padding}
              y2={svgHeight / 2}
              stroke="var(--border-subtle)"
              strokeDasharray="4 4"
            />
            <line
              x1={padding}
              y1={svgHeight - padding}
              x2={svgWidth - padding}
              y2={svgHeight - padding}
              stroke="var(--border-default)"
            />

            {/* Gradient Fill Area */}
            <polygon points={areaPoints} fill={`url(#${gradientId})`} />

            {/* Main Sparkline */}
            <polyline
              points={polylinePoints}
              fill="none"
              stroke={color}
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />

            {/* Interactive Points */}
            {points.map((p, i) => (
              <circle
                key={i}
                cx={p.x}
                cy={p.y}
                r={hoveredSample === p.sample ? 5 : 2.5}
                fill={hoveredSample === p.sample ? "var(--bg-app)" : color}
                stroke={color}
                strokeWidth={hoveredSample === p.sample ? 3 : 1}
                style={{ cursor: "pointer", transition: "r 0.15s ease" }}
                onMouseEnter={() => setHoveredSample(p.sample)}
                onMouseLeave={() => setHoveredSample(null)}
              />
            ))}
          </svg>
        </div>
      ) : (
        <div style={{ maxHeight: `${height}px`, overflowY: "auto" }}>
          <Table
            columns={[
              {
                header: "Fecha / Hora",
                cell: (s) => new Date(s.recorded_at).toLocaleString(),
              },
              {
                header: "Valor",
                cell: (s) => `${Number(s.metric_value).toFixed(2)} ${unit}`,
                align: "right",
              },
            ]}
            data={sorted.slice(-10).reverse()}
            keyExtractor={(s) => `${s.recorded_at}-${s.metric_name}`}
          />
        </div>
      )}
    </div>
  );
}
