/**
 * Controlled Remote Action contracts matching FastAPI OpenAPI schema.
 */

export type ActionCatalogType =
  | "reboot_system"
  | "restart_service"
  | "collect_extended_diagnostics"
  | "flush_dns";

export type ActionExecutionStatus =
  | "PENDING_APPROVAL"
  | "DISPATCHED"
  | "ACKNOWLEDGED"
  | "RUNNING"
  | "COMPLETED"
  | "FAILED"
  | "EXPIRED"
  | "REJECTED";

export interface ActionRequest {
  action_name: string;
  parameters: Record<string, unknown>;
}

export interface ActionResponse {
  organization_id: string;
  id: string;
  device_id: string;
  action_name: string;
  nonce: string;
  key_version: number | null;
  issued_at: string;
  expires_at: string;
  signature: string | null;
  parameters: Record<string, unknown>;
  status: ActionExecutionStatus;
}

export interface ActionListResponse {
  items: ActionResponse[];
}

export interface ActionApprovalResponse {
  id: string;
  status: string;
}

export interface ActionResultCreate {
  status: "SUCCEEDED" | "FAILED";
  exit_code: number;
  output_summary?: string | null | undefined;
}

export interface ActionResultResponse {
  status: string;
  is_replay: boolean;
}
