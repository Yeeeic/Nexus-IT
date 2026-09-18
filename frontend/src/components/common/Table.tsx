import React from "react";
import { Skeleton } from "./Skeleton";
import { EmptyState } from "./EmptyState";

export interface Column<T> {
  header: string;
  accessorKey?: keyof T;
  cell?: (item: T) => React.ReactNode;
  width?: string;
  align?: "left" | "center" | "right";
}

export interface TableProps<T> {
  columns: Column<T>[];
  data: T[];
  isLoading?: boolean;
  emptyMessage?: string;
  emptyTitle?: string;
  keyExtractor: (item: T) => string;
  onRowClick?: (item: T) => void;
}

export function Table<T>({
  columns,
  data,
  isLoading = false,
  emptyMessage = "No se encontraron registros en este módulo.",
  emptyTitle = "Sin datos disponibles",
  keyExtractor,
  onRowClick,
}: TableProps<T>) {
  if (isLoading) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
        <Skeleton height="40px" />
        <Skeleton height="50px" />
        <Skeleton height="50px" />
        <Skeleton height="50px" />
      </div>
    );
  }

  if (data.length === 0) {
    return <EmptyState title={emptyTitle} description={emptyMessage} />;
  }

  return (
    <div style={{ width: "100%", overflowX: "auto", borderRadius: "var(--radius-lg)", border: "1px solid var(--border-subtle)" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left", fontSize: "var(--text-sm)" }}>
        <thead>
          <tr style={{ backgroundColor: "var(--bg-surface-elevated)", borderBottom: "1px solid var(--border-subtle)" }}>
            {columns.map((col, idx) => (
              <th
                key={idx}
                style={{
                  padding: "0.75rem 1rem",
                  fontWeight: 600,
                  fontSize: "var(--text-xs)",
                  color: "var(--text-secondary)",
                  textTransform: "uppercase",
                  letterSpacing: "0.04em",
                  width: col.width,
                  textAlign: col.align || "left",
                }}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((item) => {
            const key = keyExtractor(item);
            return (
              <tr
                key={key}
                onClick={() => onRowClick && onRowClick(item)}
                style={{
                  borderBottom: "1px solid var(--border-subtle)",
                  backgroundColor: "var(--bg-surface)",
                  cursor: onRowClick ? "pointer" : "default",
                  transition: "background-color var(--transition-fast)",
                }}
                className={onRowClick ? "nexus-table-row-clickable" : ""}
              >
                {columns.map((col, cIdx) => (
                  <td
                    key={cIdx}
                    style={{
                      padding: "0.875rem 1rem",
                      color: "var(--text-primary)",
                      textAlign: col.align || "left",
                    }}
                  >
                    {col.cell
                      ? col.cell(item)
                      : col.accessorKey
                      ? String(item[col.accessorKey] ?? "-")
                      : "-"}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
