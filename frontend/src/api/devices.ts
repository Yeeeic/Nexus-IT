import { apiClient } from "./client";
import type {
  DeviceResponse,
  DeviceListResponse,
  DeviceEnrollmentRequest,
  DeviceEnrollmentResponse,
  DeviceUpdateRequest,
  DeviceTokenResponse,
  InventoryResponse,
} from "@/types/devices";

export const devicesApi = {
  list: async (params?: { limit?: number | undefined; after?: string | undefined }): Promise<DeviceListResponse> => {
    return apiClient<DeviceListResponse>("/devices", {
      method: "GET",
      params: {
        limit: params?.limit,
        after: params?.after,
      },
    });
  },

  getById: async (id: string): Promise<DeviceResponse> => {
    return apiClient<DeviceResponse>(`/devices/${id}`, {
      method: "GET",
    });
  },

  create: async (data: DeviceEnrollmentRequest): Promise<DeviceEnrollmentResponse> => {
    return apiClient<DeviceEnrollmentResponse>("/devices", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  update: async (id: string, data: DeviceUpdateRequest): Promise<DeviceResponse> => {
    return apiClient<DeviceResponse>(`/devices/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  },

  delete: async (id: string): Promise<void> => {
    await apiClient<void>(`/devices/${id}`, {
      method: "DELETE",
    });
  },

  getInventory: async (id: string): Promise<InventoryResponse> => {
    return apiClient<InventoryResponse>(`/devices/${id}/inventory`, {
      method: "GET",
    });
  },

  createToken: async (id: string, expiresAt?: string | null | undefined): Promise<DeviceTokenResponse> => {
    return apiClient<DeviceTokenResponse>(`/devices/${id}/tokens`, {
      method: "POST",
      body: JSON.stringify({ expires_at: expiresAt || null }),
    });
  },

  disconnect: async (id: string): Promise<void> => {
    await apiClient<void>(`/devices/${id}/disconnect`, {
      method: "POST",
    });
  },

  assignUser: async (deviceId: string, userId: string): Promise<void> => {
    await apiClient<void>(`/devices/${deviceId}/assignments`, {
      method: "POST",
      body: JSON.stringify({ user_id: userId }),
    });
  },

  unassignUser: async (deviceId: string, userId: string): Promise<void> => {
    await apiClient<void>(`/devices/${deviceId}/assignments/${userId}`, {
      method: "DELETE",
    });
  },
};
