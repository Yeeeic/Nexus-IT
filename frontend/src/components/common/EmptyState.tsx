import React from "react";
import { Inbox } from "lucide-react";
import { Button } from "./Button";

export interface EmptyStateProps {
  title: string;
  description?: string;
  icon?: React.ReactNode;
  actionLabel?: string;
  onAction?: () => void;
}

export function EmptyState({
  title,
  description,
  icon,
  actionLabel,
  onAction,
}: EmptyStateProps) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "3rem 1.5rem",
        textAlign: "center",
        backgroundColor: "var(--bg-surface)",
        border: "1px dashed var(--border-default)",
        borderRadius: "var(--radius-lg)",
      }}
    >
      <div
        style={{
          width: "48px",
          height: "48px",
          borderRadius: "var(--radius-full)",
          backgroundColor: "var(--bg-surface-elevated)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--text-muted)",
          marginBottom: "1rem",
        }}
      >
        {icon || <Inbox size={24} />}
      </div>
      <h3 style={{ fontSize: "var(--text-base)", fontWeight: 600, color: "var(--text-primary)" }}>
        {title}
      </h3>
      {description && (
        <p
          style={{
            fontSize: "var(--text-sm)",
            color: "var(--text-secondary)",
            maxWidth: "400px",
            marginTop: "0.25rem",
            marginBottom: actionLabel ? "1.25rem" : 0,
          }}
        >
          {description}
        </p>
      )}
      {actionLabel && onAction && (
        <Button variant="primary" size="sm" onClick={onAction}>
          {actionLabel}
        </Button>
      )}
    </div>
  );
}
