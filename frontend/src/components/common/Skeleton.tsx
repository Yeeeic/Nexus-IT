import React from "react";

export interface SkeletonProps {
  width?: string;
  height?: string;
  borderRadius?: string;
  className?: string;
  style?: React.CSSProperties;
}

export function Skeleton({
  width = "100%",
  height = "20px",
  borderRadius = "var(--radius-md)",
  className = "",
  style,
}: SkeletonProps) {
  return (
    <div
      className={`nexus-skeleton ${className}`}
      style={{
        width,
        height,
        borderRadius,
        backgroundColor: "var(--bg-surface-hover)",
        opacity: 0.7,
        animation: "pulse-glow 1.5s ease-in-out infinite",
        ...style,
      }}
    />
  );
}
