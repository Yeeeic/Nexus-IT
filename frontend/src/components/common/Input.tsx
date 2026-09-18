import React, { type InputHTMLAttributes, forwardRef } from "react";

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  helperText?: string;
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, helperText, leftIcon, rightIcon, id, disabled, style, className = "", ...props }, ref) => {
    const inputId = id || (label ? label.toLowerCase().replace(/\s+/g, "-") : undefined);

    return (
      <div style={{ display: "flex", flexDirection: "column", gap: "0.375rem", width: "100%" }}>
        {label && (
          <label
            htmlFor={inputId}
            style={{
              fontSize: "var(--text-xs)",
              fontWeight: 500,
              color: error ? "var(--status-critical)" : "var(--text-secondary)",
              letterSpacing: "0.02em",
            }}
          >
            {label}
          </label>
        )}
        <div style={{ position: "relative", display: "flex", alignItems: "center", width: "100%" }}>
          {leftIcon && (
            <div
              style={{
                position: "absolute",
                left: "0.75rem",
                display: "flex",
                alignItems: "center",
                color: "var(--text-muted)",
                pointerEvents: "none",
              }}
            >
              {leftIcon}
            </div>
          )}
          <input
            ref={ref}
            id={inputId}
            disabled={disabled}
            aria-invalid={Boolean(error)}
            aria-describedby={error ? `${inputId}-error` : helperText ? `${inputId}-helper` : undefined}
            style={{
              width: "100%",
              height: "40px",
              padding: `0 0.875rem 0 ${leftIcon ? "2.5rem" : "0.875rem"}`,
              backgroundColor: "var(--bg-input)",
              color: "var(--text-primary)",
              border: `1px solid ${error ? "var(--status-critical)" : "var(--border-default)"}`,
              borderRadius: "var(--radius-md)",
              fontSize: "var(--text-sm)",
              fontFamily: "var(--font-sans)",
              outline: "none",
              transition: "border-color var(--transition-fast)",
              opacity: disabled ? 0.6 : 1,
              cursor: disabled ? "not-allowed" : "text",
              ...style,
            }}
            className={`nexus-input ${className}`}
            {...props}
          />
          {rightIcon && (
            <div
              style={{
                position: "absolute",
                right: "0.75rem",
                display: "flex",
                alignItems: "center",
                color: "var(--text-muted)",
              }}
            >
              {rightIcon}
            </div>
          )}
        </div>
        {error ? (
          <span id={`${inputId}-error`} style={{ fontSize: "var(--text-xs)", color: "var(--status-critical)" }}>
            {error}
          </span>
        ) : helperText ? (
          <span id={`${inputId}-helper`} style={{ fontSize: "var(--text-xs)", color: "var(--text-muted)" }}>
            {helperText}
          </span>
        ) : null}
      </div>
    );
  }
);

Input.displayName = "Input";
