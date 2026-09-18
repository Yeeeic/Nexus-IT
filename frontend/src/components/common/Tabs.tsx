import React from "react";

export interface TabItem {
  id: string;
  label: string;
  count?: number;
  icon?: React.ReactNode;
}

export interface TabsProps {
  tabs: TabItem[];
  activeTab: string;
  onChange: (tabId: string) => void;
  className?: string;
}

export function Tabs({ tabs, activeTab, onChange, className = "" }: TabsProps) {
  return (
    <div
      role="tablist"
      style={{
        display: "flex",
        alignItems: "center",
        gap: "0.25rem",
        borderBottom: "1px solid var(--border-subtle)",
        width: "100%",
        overflowX: "auto",
      }}
      className={`nexus-tabs ${className}`}
    >
      {tabs.map((tab) => {
        const isActive = tab.id === activeTab;
        return (
          <button
            key={tab.id}
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(tab.id)}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "0.5rem",
              padding: "0.75rem 1rem",
              fontSize: "var(--text-sm)",
              fontWeight: isActive ? 600 : 500,
              color: isActive ? "var(--brand-primary)" : "var(--text-secondary)",
              background: "transparent",
              border: "none",
              borderBottom: isActive ? "2px solid var(--brand-primary)" : "2px solid transparent",
              cursor: "pointer",
              transition: "all var(--transition-fast)",
              whiteSpace: "nowrap",
              marginBottom: "-1px",
            }}
          >
            {tab.icon}
            <span>{tab.label}</span>
            {tab.count !== undefined && (
              <span
                style={{
                  fontSize: "var(--text-2xs)",
                  padding: "1px 6px",
                  borderRadius: "var(--radius-full)",
                  backgroundColor: isActive ? "var(--brand-glow)" : "var(--bg-surface-elevated)",
                  color: isActive ? "var(--brand-primary)" : "var(--text-muted)",
                }}
              >
                {tab.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
