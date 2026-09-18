import { apiClient } from "./client";
import type {
  UserListResponse,
  UserSummaryResponse,
  RoleResponse,
  RoleListResponse,
  RoleCreateRequest,
  PermissionListResponse,
  AuditLogListResponse,
} from "@/types/admin";

export interface UserCreateInput {
  email: string;
  full_name: string;
  password: string;
  role?: "ADMIN" | "TECHNICIAN" | "READER";
}

export const adminApi = {
  listUsers: async (params?: { limit?: number | undefined; after?: string | undefined }): Promise<UserListResponse> => {
    return apiClient<UserListResponse>("/users", {
      method: "GET",
      params: {
        limit: params?.limit,
        after: params?.after,
      },
    });
  },

  createUser: async (data: UserCreateInput): Promise<UserSummaryResponse> => {
    return apiClient<UserSummaryResponse>("/users", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  toggleUserStatus: async (userId: string, isActive: boolean): Promise<UserSummaryResponse> => {
    return apiClient<UserSummaryResponse>(`/users/${userId}/status`, {
      method: "PATCH",
      body: JSON.stringify({ is_active: isActive }),
    });
  },

  revokeUserSessions: async (userId: string): Promise<{ revoked_sessions: number; user_id: string }> => {
    return apiClient<{ revoked_sessions: number; user_id: string }>(`/users/${userId}/revoke-sessions`, {
      method: "POST",
    });
  },

  deleteUser: async (userId: string): Promise<void> => {
    await apiClient<void>(`/users/${userId}`, {
      method: "DELETE",
    });
  },

  listRoles: async (): Promise<RoleListResponse> => {
    return apiClient<RoleListResponse>("/roles", {
      method: "GET",
    });
  },

  createRole: async (data: RoleCreateRequest): Promise<RoleResponse> => {
    return apiClient<RoleResponse>("/roles", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  assignRole: async (roleId: string, userId: string): Promise<void> => {
    await apiClient<void>(`/roles/${roleId}/assignments`, {
      method: "POST",
      body: JSON.stringify({ user_id: userId }),
    });
  },

  listPermissions: async (): Promise<PermissionListResponse> => {
    return apiClient<PermissionListResponse>("/permissions", {
      method: "GET",
    });
  },

  listAuditLogs: async (params?: {
    limit?: number | undefined;
    before?: string | undefined;
    action?: string | undefined;
  }): Promise<AuditLogListResponse> => {
    return apiClient<AuditLogListResponse>("/audit-logs", {
      method: "GET",
      params: {
        limit: params?.limit,
        before: params?.before,
        action: params?.action,
      },
    });
  },
};
