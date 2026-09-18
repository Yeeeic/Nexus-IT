import React from "react";

export type BadgeVariant = "healthy" | "warning" | "critical" | "info" | "offline";

export interface BadgeProps {
  children: React.ReactNode;
  variant?: BadgeVariant;
  dot?: boolean;
  className?: string;
  style?: React.CSSProperties;
}

export function Badge({ children, variant = "info", dot = false, className = "", style }: BadgeProps) {
  return (
    <span className={`badge badge-${variant} ${className}`} style={style}>
      {dot && <span className={`status-dot ${variant}`} />}
      {children}
    </span>
  );
}
