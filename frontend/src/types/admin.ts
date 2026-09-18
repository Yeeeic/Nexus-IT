/**
 * RBAC, Administration and Audit contracts matching FastAPI OpenAPI schema.
 */

export interface PermissionItem {
  code: string;
  name: string;
  description: string;
}

export interface PermissionListResponse {
  items: PermissionItem[];
}

export interface RoleResponse {
  id: string;
  name: string;
  description: string;
  is_system: boolean;
  permissions: string[];
}

export interface RoleListResponse {
  items: RoleResponse[];
}

export interface RoleCreateRequest {
  name: string;
  description: string;
  permissions: string[];
}

export interface RoleAssignmentRequest {
  user_id: string;
}

export interface AuditLogResponse {
  id: string;
  actor_id: string | null;
  actor_type: "USER" | "AGENT" | "SYSTEM";
  action: string;
  resource_type: string;
  resource_id: string | null;
  status: "SUCCESS" | "FAILURE" | "DENIED";
  details: Record<string, string>;
  created_at: string;
}

export interface AuditLogListResponse {
  items: AuditLogResponse[];
}

export interface UserSummaryResponse {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
}

export interface UserListResponse {
  items: UserSummaryResponse[];
  next_cursor: string | null;
}
