/**
 * Utility to accurately calculate device connection heartbeat status.
 * Devices transmitting telemetry within the last 60 seconds are ONLINE.
 * Devices stopped, disconnected, or without recent heartbeat are OFFLINE.
 */
export function isDeviceOnline(device: { is_active?: boolean; last_seen_at?: string | null }): boolean {
  if (!device.is_active || !device.last_seen_at) return false;
  const lastSeen = new Date(device.last_seen_at).getTime();
  if (isNaN(lastSeen)) return false;
  const now = Date.now();
  const diffMs = now - lastSeen;
  // Tolerate sub-minute differences and minor clock skew between host/VM
  return diffMs <= 60000 && diffMs >= -30000;
}

export function getDeviceStatus(device: { is_active?: boolean; last_seen_at?: string | null }): "ONLINE" | "OFFLINE" {
  return isDeviceOnline(device) ? "ONLINE" : "OFFLINE";
}
