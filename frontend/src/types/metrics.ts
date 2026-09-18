/**
 * Metrics, Telemetry, Alerts, and DLQ contracts matching FastAPI OpenAPI schema.
 */

export type AlertSeverity = "INFO" | "WARNING" | "CRITICAL";
export type AlertStatus = "OPEN" | "ACKNOWLEDGED" | "RESOLVED" | "SUPPRESSED";
export type ComparisonOperator = "GT" | "GTE" | "LT" | "LTE" | "EQ";
export type BatchStatus =
  | "RECEIVED"
  | "PROCESSING"
  | "PROCESSED"
  | "DLQ"
  | "AWAITING_REUPLOAD"
  | "DLQ_EXHAUSTED";

export interface TelemetrySampleResponse {
  id: string;
  device_id: string;
  metric_name: string;
  metric_value: number;
  recorded_at: string;
  labels: Record<string, string>;
}

export type TelemetrySample = TelemetrySampleResponse;

export interface TelemetryResponse {
  items: TelemetrySampleResponse[];
}

export interface AlertRuleInput {
  name: string;
  metric_name: string;
  operator: ComparisonOperator;
  threshold_value: number;
  duration_seconds: number;
  severity: AlertSeverity;
}

export interface AlertRuleResponse {
  id: string;
  name: string;
  metric_name: string;
  operator: ComparisonOperator;
  threshold_value: number;
  duration_seconds: number;
  severity: AlertSeverity;
  is_enabled: boolean;
  created_at: string;
}

export interface AlertRuleListResponse {
  items: AlertRuleResponse[];
}

export interface AlertResponse {
  id: string;
  device_id: string;
  alert_rule_id: string | null;
  severity: AlertSeverity;
  status: AlertStatus;
  message: string;
  triggered_at: string;
  resolved_at: string | null;
}

export interface AlertListResponse {
  items: AlertResponse[];
}

export interface BatchStatusResponse {
  batch_id: string;
  status: BatchStatus;
  retry_count: number;
  reprocess_count: number;
  error_code: string | null;
  decision: "PURGE_LOCAL" | "RETAIN" | null;
}

export interface BatchStatusQueryResponse {
  statuses: BatchStatusResponse[];
}

export interface BatchDiagnosticsResponse {
  batch_id: string;
  status: BatchStatus;
  retry_count: number;
  reprocess_count: number;
  payload_digest: string;
  error_code: string | null;
  error_summary: string | null;
  received_at: string;
  processed_at: string | null;
}

export interface BatchRetryInput {
  reason: string;
}

export interface BatchDecisionInput {
  action: "PURGE_LOCAL" | "RETAIN";
  reason: string;
}
