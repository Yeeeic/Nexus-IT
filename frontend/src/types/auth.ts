/**
 * Authentication and Session DTOs matching backend/app/auth/schemas.py
 */

export interface OrganizationMembershipItem {
  organization_id: string;
  organization_name: string;
  slug: string;
}

export interface UserMeResponse {
  user_id: string;
  email: string;
  full_name: string;
  organization_id: string | null;
  permissions: string[];
  available_organizations: OrganizationMembershipItem[];
}

export type LoginStatus = "AUTHENTICATED" | "ORGANIZATION_SELECTION_REQUIRED";

export interface LoginResponse {
  status: LoginStatus;
  user_id: string;
  email: string;
  full_name: string;
  active_organization: OrganizationMembershipItem | null;
  available_organizations: OrganizationMembershipItem[];
}

export interface LoginCredentials {
  email: string;
  password: string;
}

export interface AuthContextSelectInput {
  organization_id: string;
}

export interface PasswordResetRequestInput {
  email: string;
}

export interface PasswordResetConfirmInput {
  token: string;
  new_password: string;
}
