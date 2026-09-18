import { apiClient } from "./client";
import type {
  ActionRequest,
  ActionResponse,
  ActionListResponse,
  ActionApprovalResponse,
} from "@/types/actions";

export const actionsApi = {
  listByDevice: async (
    deviceId: string,
    limit?: number | undefined
  ): Promise<ActionListResponse> => {
    return apiClient<ActionListResponse>(`/devices/${deviceId}/actions`, {
      method: "GET",
      params: {
        limit,
      },
    });
  },

  create: async (
    deviceId: string,
    data: ActionRequest
  ): Promise<ActionResponse> => {
    return apiClient<ActionResponse>(`/devices/${deviceId}/actions`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  submitApproval: async (actionId: string): Promise<ActionApprovalResponse> => {
    return apiClient<ActionApprovalResponse>(`/actions/${actionId}/approval`, {
      method: "POST",
    });
  },
};
