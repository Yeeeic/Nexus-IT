import { createContext, useContext, useState, useCallback, type ReactNode } from "react";

export type NotificationType = "success" | "error" | "warning" | "info";

export interface NotificationItem {
  id: string;
  type: NotificationType;
  title: string;
  message?: string | undefined;
  errorId?: string | undefined;
  durationMs?: number | undefined;
}

interface NotificationContextType {
  notifications: NotificationItem[];
  notify: (notification: Omit<NotificationItem, "id">) => string;
  dismiss: (id: string) => void;
  success: (title: string, message?: string | undefined) => void;
  error: (title: string, message?: string | undefined, errorId?: string | undefined) => void;
  warning: (title: string, message?: string | undefined) => void;
  info: (title: string, message?: string | undefined) => void;
}

const NotificationContext = createContext<NotificationContextType | undefined>(undefined);

export function NotificationProvider({ children }: { children: ReactNode }) {
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);

  const dismiss = useCallback((id: string) => {
    setNotifications((prev) => prev.filter((n) => n.id !== id));
  }, []);

  const notify = useCallback(
    ({ durationMs = 5000, ...rest }: Omit<NotificationItem, "id">) => {
      const id = Math.random().toString(36).substring(2, 9);
      const newNotification: NotificationItem = { id, durationMs, ...rest };

      setNotifications((prev) => {
        // Prevent duplicate identical alerts from stacking up
        const isDuplicate = prev.some(
          (n) => n.title === rest.title && n.message === rest.message && n.type === rest.type
        );
        if (isDuplicate) return prev;
        return [...prev, newNotification];
      });

      if (durationMs > 0) {
        setTimeout(() => {
          dismiss(id);
        }, durationMs);
      }
      return id;
    },
    [dismiss]
  );

  const success = useCallback(
    (title: string, message?: string) => notify({ type: "success", title, message }),
    [notify]
  );

  const error = useCallback(
    (title: string, message?: string, errorId?: string) =>
      notify({ type: "error", title, message, errorId, durationMs: 7000 }),
    [notify]
  );

  const warning = useCallback(
    (title: string, message?: string) => notify({ type: "warning", title, message }),
    [notify]
  );

  const info = useCallback(
    (title: string, message?: string) => notify({ type: "info", title, message }),
    [notify]
  );

  return (
    <NotificationContext.Provider
      value={{ notifications, notify, dismiss, success, error, warning, info }}
    >
      {children}
      {/* Notification Toast Container */}
      <div
        aria-live="polite"
        style={{
          position: "fixed",
          bottom: "1.5rem",
          right: "1.5rem",
          zIndex: "var(--z-toast)",
          display: "flex",
          flexDirection: "column",
          gap: "0.75rem",
          maxWidth: "400px",
          width: "calc(100vw - 3rem)",
          pointerEvents: "none",
        }}
      >
        {notifications.map((n) => (
          <div
            key={n.id}
            role="alert"
            className="nexus-card nexus-card-elevated"
            style={{
              pointerEvents: "auto",
              padding: "0.875rem 1rem",
              borderLeft: `4px solid ${
                n.type === "success"
                  ? "var(--status-healthy)"
                  : n.type === "error"
                  ? "var(--status-critical)"
                  : n.type === "warning"
                  ? "var(--status-warning)"
                  : "var(--status-info)"
              }`,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "flex-start",
              gap: "0.75rem",
              boxShadow: "var(--shadow-lg)",
            }}
          >
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 600, fontSize: "var(--text-sm)" }}>{n.title}</div>
              {n.message && (
                <div style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)", marginTop: "0.25rem" }}>
                  {n.message}
                </div>
              )}
              {n.errorId && (
                <div style={{ fontSize: "var(--text-2xs)", color: "var(--text-muted)", marginTop: "0.25rem", fontFamily: "var(--font-mono)" }}>
                  ID de referencia: {n.errorId}
                </div>
              )}
            </div>
            <button
              onClick={() => dismiss(n.id)}
              aria-label="Cerrar notificación"
              style={{
                background: "transparent",
                border: "none",
                color: "var(--text-muted)",
                cursor: "pointer",
                padding: "2px",
                fontSize: "1rem",
                lineHeight: 1,
              }}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </NotificationContext.Provider>
  );
}

export function useNotification() {
  const context = useContext(NotificationContext);
  if (!context) {
    throw new Error("useNotification must be used within a NotificationProvider");
  }
  return context;
}
