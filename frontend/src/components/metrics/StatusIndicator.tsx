import { Badge, type BadgeVariant } from "../common/Badge";

export interface StatusIndicatorProps {
  status: "ONLINE" | "OFFLINE" | "WARNING" | "CRITICAL" | "UNKNOWN" | string;
  showLabel?: boolean;
}

export function StatusIndicator({ status, showLabel = true }: StatusIndicatorProps) {
  const normalized = status.toUpperCase();

  const getVariant = (): BadgeVariant => {
    switch (normalized) {
      case "ONLINE":
      case "HEALTHY":
      case "PROCESSED":
      case "SUCCESS":
        return "healthy";
      case "WARNING":
      case "WAITING_CUSTOMER":
      case "AWAITING_REUPLOAD":
        return "warning";
      case "CRITICAL":
      case "DLQ":
      case "FAILED":
      case "DLQ_EXHAUSTED":
        return "critical";
      case "OFFLINE":
      case "CLOSED":
        return "offline";
      default:
        return "info";
    }
  };

  const getLabel = (): string => {
    switch (normalized) {
      case "ONLINE":
        return "En línea";
      case "OFFLINE":
        return "Desconectado";
      case "WARNING":
        return "Advertencia";
      case "CRITICAL":
        return "Crítico";
      case "HEALTHY":
        return "Saludable";
      case "PROCESSED":
        return "Procesado";
      case "DLQ":
        return "En cola DLQ";
      case "AWAITING_REUPLOAD":
        return "Re-subida requerida";
      case "OPEN":
        return "Abierto";
      case "IN_PROGRESS":
        return "En atención";
      case "RESOLVED":
        return "Resuelto";
      case "CLOSED":
        return "Cerrado";
      default:
        return status;
    }
  };

  return (
    <Badge variant={getVariant()} dot>
      {showLabel ? getLabel() : ""}
    </Badge>
  );
}
