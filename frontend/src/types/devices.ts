/**
 * Device and Inventory API Contracts matching FastAPI OpenAPI schemas.
 */

export type DeviceHealthStatus = "ONLINE" | "OFFLINE" | "WARNING" | "CRITICAL";

export interface DeviceResponse {
  id: string;
  hostname: string;
  display_name: string | null;
  is_active: boolean;
  last_seen_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface DeviceListResponse {
  items: DeviceResponse[];
  next_cursor: string | null;
}

export interface DeviceEnrollmentRequest {
  hostname: string;
  display_name?: string | null | undefined;
  token_expires_at?: string | null | undefined;
}

export interface DeviceEnrollmentResponse extends DeviceResponse {
  token_id: string;
  token: string;
  token_expires_at: string | null;
}

export interface DeviceTokenResponse {
  token_id: string;
  token: string;
  expires_at: string | null;
}

export interface DeviceUpdateRequest {
  display_name?: string | null | undefined;
}

export interface DeviceAssignmentRequest {
  user_id: string;
}

export interface HardwareInventory {
  cpu_model: string | null;
  physical_cores: number | null;
  logical_processors: number | null;
  memory_bytes: number;
}

export interface SoftwarePackage {
  name: string;
  version: string | null;
  publisher: string | null;
  architecture: "X86" | "X64" | "ARM" | "ARM64" | "OTHER";
}

export interface PatchInventory {
  identifier: string;
  status: string;
}

export interface ServiceInventory {
  name: string;
  display_name: string;
  status: string;
  start_type: string;
}

export interface InventoryResponse {
  device_id: string;
  hardware: HardwareInventory | Record<string, unknown>;
  software_packages: SoftwarePackage[];
  patches: PatchInventory[];
  services: ServiceInventory[];
  collected_at: string;
  updated_at: string;
}
