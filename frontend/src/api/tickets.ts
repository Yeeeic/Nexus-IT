import { apiClient } from "./client";
import type {
  TicketCreate,
  TicketResponse,
  TicketListResponse,
  TicketTransition,
  TicketStatusResponse,
  CommentCreate,
  CommentResponse,
  CommentListResponse,
  AttachmentResponse,
} from "@/types/tickets";

export const ticketsApi = {
  list: async (params?: { limit?: number | undefined; after?: string | undefined }): Promise<TicketListResponse> => {
    return apiClient<TicketListResponse>("/tickets", {
      method: "GET",
      params: {
        limit: params?.limit,
        after: params?.after,
      },
    });
  },

  getById: async (id: string): Promise<TicketResponse> => {
    return apiClient<TicketResponse>(`/tickets/${id}`, {
      method: "GET",
    });
  },

  create: async (data: TicketCreate): Promise<TicketResponse> => {
    return apiClient<TicketResponse>("/tickets", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  listComments: async (
    ticketId: string,
    params?: { limit?: number | undefined; after?: string | undefined }
  ): Promise<CommentListResponse> => {
    return apiClient<CommentListResponse>(`/tickets/${ticketId}/comments`, {
      method: "GET",
      params: {
        limit: params?.limit,
        after: params?.after,
      },
    });
  },

  addComment: async (ticketId: string, data: CommentCreate): Promise<CommentResponse> => {
    return apiClient<CommentResponse>(`/tickets/${ticketId}/comments`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  transition: async (ticketId: string, data: TicketTransition): Promise<TicketStatusResponse> => {
    return apiClient<TicketStatusResponse>(`/tickets/${ticketId}/status`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  },

  uploadAttachment: async (ticketId: string, file: File): Promise<AttachmentResponse> => {
    const arrayBuffer = await file.arrayBuffer();
    return apiClient<AttachmentResponse>(`/tickets/${ticketId}/attachments`, {
      method: "POST",
      headers: {
        "Content-Type": file.type || "application/octet-stream",
        "X-File-Name": file.name,
      },
      body: arrayBuffer,
    });
  },

  getAttachmentUrl: (ticketId: string, attachmentId: string): string => {
    return `/api/v1/tickets/${ticketId}/attachments/${attachmentId}`;
  },

  delete: async (ticketId: string): Promise<void> => {
    await apiClient<void>(`/tickets/${ticketId}`, {
      method: "DELETE",
    });
  },

  deleteAttachment: async (ticketId: string, attachmentId: string): Promise<void> => {
    await apiClient<void>(`/tickets/${ticketId}/attachments/${attachmentId}`, {
      method: "DELETE",
    });
  },
};
