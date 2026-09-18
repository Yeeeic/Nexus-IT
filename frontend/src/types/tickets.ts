/**
 * Help Desk Tickets, Comments, and Attachments contracts matching FastAPI OpenAPI schema.
 */

export type TicketStatus =
  | "OPEN"
  | "IN_PROGRESS"
  | "WAITING_CUSTOMER"
  | "RESOLVED"
  | "CLOSED";

export type TicketPriority = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export interface TicketCreate {
  device_id?: string | null | undefined;
  alert_id?: string | null | undefined;
  title: string;
  description: string;
  priority: TicketPriority;
}

export interface TicketResponse {
  id: string;
  device_id: string | null;
  alert_id: string | null;
  created_by: string;
  assigned_to: string | null;
  ticket_number: string;
  title: string;
  description: string;
  status: TicketStatus;
  priority: TicketPriority;
  resolved_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface TicketListResponse {
  items: TicketResponse[];
  next_cursor: string | null;
}

export interface TicketTransition {
  expected_status?: TicketStatus | undefined;
  status: TicketStatus;
  assigned_to?: string | null | undefined;
}

export interface TicketStatusResponse {
  id: string;
  status: TicketStatus;
}

export interface CommentCreate {
  content: string;
  is_internal?: boolean | undefined;
}

export interface CommentResponse {
  id: string;
  ticket_id: string;
  user_id: string;
  is_internal: boolean;
  content: string;
  created_at: string;
}

export interface CommentListResponse {
  items: CommentResponse[];
  next_cursor: string | null;
}

export interface AttachmentResponse {
  id: string;
  ticket_id: string;
  original_name: string;
  mime_type: string;
  file_size: number;
  uploaded_at: string;
}
