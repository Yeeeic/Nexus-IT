import React, { type ButtonHTMLAttributes } from "react";

export type ButtonVariant = "primary" | "secondary" | "danger" | "ghost" | "outline";
export type ButtonSize = "sm" | "md" | "lg";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  isLoading?: boolean;
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
}

export function Button({
  children,
  variant = "primary",
  size = "md",
  isLoading = false,
  leftIcon,
  rightIcon,
  disabled,
  className = "",
  style,
  ...props
}: ButtonProps) {
  const getVariantStyles = (): React.CSSProperties => {
    switch (variant) {
      case "primary":
        return {
          backgroundColor: "var(--brand-primary)",
          color: "#ffffff",
          border: "1px solid transparent",
          boxShadow: "0 1px 2px rgba(14, 165, 233, 0.2)",
        };
      case "secondary":
        return {
          backgroundColor: "var(--bg-surface-elevated)",
          color: "var(--text-primary)",
          border: "1px solid var(--border-default)",
        };
      case "danger":
        return {
          backgroundColor: "var(--status-critical)",
          color: "#ffffff",
          border: "1px solid transparent",
        };
      case "outline":
        return {
          backgroundColor: "transparent",
          color: "var(--text-primary)",
          border: "1px solid var(--border-strong)",
        };
      case "ghost":
        return {
          backgroundColor: "transparent",
          color: "var(--text-secondary)",
          border: "1px solid transparent",
        };
    }
  };

  const getSizeStyles = (): React.CSSProperties => {
    switch (size) {
      case "sm":
        return { padding: "0.375rem 0.75rem", fontSize: "var(--text-xs)", height: "32px" };
      case "md":
        return { padding: "0.5rem 1rem", fontSize: "var(--text-sm)", height: "40px" };
      case "lg":
        return { padding: "0.625rem 1.25rem", fontSize: "var(--text-base)", height: "48px" };
    }
  };

  return (
    <button
      disabled={disabled || isLoading}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        gap: "0.5rem",
        borderRadius: "var(--radius-md)",
        fontWeight: 500,
        cursor: disabled || isLoading ? "not-allowed" : "pointer",
        opacity: disabled || isLoading ? 0.6 : 1,
        transition: "all var(--transition-fast)",
        fontFamily: "var(--font-sans)",
        userSelect: "none",
        ...getVariantStyles(),
        ...getSizeStyles(),
        ...style,
      }}
      className={`nexus-btn ${className}`}
      {...props}
    >
      {isLoading ? (
        <span
          style={{
            width: "14px",
            height: "14px",
            border: "2px solid currentColor",
            borderRightColor: "transparent",
            borderRadius: "50%",
            animation: "spin 0.6s linear infinite",
            display: "inline-block",
          }}
        />
      ) : (
        leftIcon
      )}
      <span>{children}</span>
      {!isLoading && rightIcon}
    </button>
  );
}
