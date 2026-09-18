import { type SelectHTMLAttributes, forwardRef } from "react";

export interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  error?: string;
  helperText?: string;
  options: SelectOption[];
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ label, error, helperText, options, id, disabled, style, className = "", ...props }, ref) => {
    const selectId = id || (label ? label.toLowerCase().replace(/\s+/g, "-") : undefined);

    return (
      <div style={{ display: "flex", flexDirection: "column", gap: "0.375rem", width: "100%" }}>
        {label && (
          <label
            htmlFor={selectId}
            style={{
              fontSize: "var(--text-xs)",
              fontWeight: 500,
              color: error ? "var(--status-critical)" : "var(--text-secondary)",
            }}
          >
            {label}
          </label>
        )}
        <select
          ref={ref}
          id={selectId}
          disabled={disabled}
          aria-invalid={Boolean(error)}
          style={{
            width: "100%",
            height: "40px",
            padding: "0 0.875rem",
            backgroundColor: "var(--bg-input)",
            color: "var(--text-primary)",
            border: `1px solid ${error ? "var(--status-critical)" : "var(--border-default)"}`,
            borderRadius: "var(--radius-md)",
            fontSize: "var(--text-sm)",
            fontFamily: "var(--font-sans)",
            outline: "none",
            cursor: disabled ? "not-allowed" : "pointer",
            opacity: disabled ? 0.6 : 1,
            ...style,
          }}
          className={`nexus-select ${className}`}
          {...props}
        >
          {options.map((opt) => (
            <option key={opt.value} value={opt.value} disabled={opt.disabled} style={{ background: "var(--bg-surface)", color: "var(--text-primary)" }}>
              {opt.label}
            </option>
          ))}
        </select>
        {error ? (
          <span style={{ fontSize: "var(--text-xs)", color: "var(--status-critical)" }}>{error}</span>
        ) : helperText ? (
          <span style={{ fontSize: "var(--text-xs)", color: "var(--text-muted)" }}>{helperText}</span>
        ) : null}
      </div>
    );
  }
);

Select.displayName = "Select";
