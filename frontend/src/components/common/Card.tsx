import React, { type HTMLAttributes } from "react";

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  variant?: "default" | "elevated" | "interactive";
  header?: React.ReactNode;
  footer?: React.ReactNode;
}

export function Card({
  children,
  variant = "default",
  header,
  footer,
  className = "",
  style,
  ...props
}: CardProps) {
  return (
    <div
      className={`nexus-card ${variant === "elevated" ? "nexus-card-elevated" : ""} ${className}`}
      style={{
        display: "flex",
        flexDirection: "column",
        cursor: variant === "interactive" ? "pointer" : "default",
        ...style,
      }}
      {...props}
    >
      {header && (
        <div
          style={{
            paddingBottom: "var(--space-4)",
            marginBottom: "var(--space-4)",
            borderBottom: "1px solid var(--border-subtle)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          {header}
        </div>
      )}
      <div style={{ flex: 1 }}>{children}</div>
      {footer && (
        <div
          style={{
            paddingTop: "var(--space-4)",
            marginTop: "var(--space-4)",
            borderTop: "1px solid var(--border-subtle)",
            display: "flex",
            alignItems: "center",
            justifyContent: "flex-end",
            gap: "var(--space-2)",
          }}
        >
          {footer}
        </div>
      )}
    </div>
  );
}
