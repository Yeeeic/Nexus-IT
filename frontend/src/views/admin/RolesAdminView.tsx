import React, { useEffect, useState, useCallback } from "react";
import { adminApi } from "@/api/admin";
import type { RoleResponse, PermissionItem, RoleCreateRequest } from "@/types/admin";
import { Table } from "@/components/common/Table";
import { Button } from "@/components/common/Button";
import { Badge } from "@/components/common/Badge";
import { Card } from "@/components/common/Card";
import { Modal } from "@/components/common/Modal";
import { Input } from "@/components/common/Input";
import { useNotification } from "@/context/NotificationContext";
import { Shield, Plus, RefreshCw } from "lucide-react";

export function RolesAdminView() {
  const { success, error: notifyError } = useNotification();
  const [roles, setRoles] = useState<RoleResponse[]>([]);
  const [permissions, setPermissions] = useState<PermissionItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  // Create Role Modal state
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [newRoleName, setNewRoleName] = useState("");
  const [newRoleDescription, setNewRoleDescription] = useState("");
  const [selectedPermissions, setSelectedPermissions] = useState<string[]>([]);
  const [isCreating, setIsCreating] = useState(false);

  const loadData = useCallback(async () => {
    setIsLoading(true);
    try {
      const [rList, pList] = await Promise.all([
        adminApi.listRoles().catch(() => ({ items: [] })),
        adminApi.listPermissions().catch(() => ({ items: [] })),
      ]);
      setRoles(rList.items);
      setPermissions(pList.items);
    } catch (err: any) {
      notifyError("Error al cargar roles y permisos", err.message);
    } finally {
      setIsLoading(false);
    }
  }, [notifyError]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const togglePermission = (code: string) => {
    setSelectedPermissions((prev) =>
      prev.includes(code) ? prev.filter((p) => p !== code) : [...prev, code]
    );
  };

  const handleCreateRole = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newRoleName.trim() || selectedPermissions.length === 0) return;

    setIsCreating(true);
    try {
      const input: RoleCreateRequest = {
        name: newRoleName.trim(),
        description: newRoleDescription.trim(),
        permissions: selectedPermissions,
      };

      const created = await adminApi.createRole(input);
      success("Rol personalizado creado exitosamente", `Rol: ${created.name}`);
      setIsCreateOpen(false);
      setNewRoleName("");
      setNewRoleDescription("");
      setSelectedPermissions([]);
      await loadData();
    } catch (err: any) {
      notifyError("Error al crear rol", err.message);
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "1rem" }}>
        <p style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)" }}>
          Definición de roles del sistema y políticas de acceso con privilegios canónicos
        </p>
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <Button
            variant="secondary"
            size="sm"
            onClick={loadData}
            isLoading={isLoading}
            leftIcon={<RefreshCw size={14} />}
          >
            Actualizar
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => setIsCreateOpen(true)}
            leftIcon={<Plus size={14} />}
          >
            Crear Rol Personalizado
          </Button>
        </div>
      </div>

      <Card>
        <Table
          columns={[
            {
              header: "Nombre del Rol",
              cell: (r) => (
                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                  <Shield size={16} color={r.is_system ? "var(--brand-primary)" : "var(--brand-secondary)"} />
                  <span style={{ fontWeight: 600 }}>{r.name}</span>
                </div>
              ),
              width: "180px",
            },
            {
              header: "Descripción",
              accessorKey: "description",
            },
            {
              header: "Tipo",
              cell: (r) => (
                <Badge variant={r.is_system ? "info" : "healthy"}>
                  {r.is_system ? "Sistema (Protegido)" : "Personalizado"}
                </Badge>
              ),
              width: "160px",
            },
            {
              header: "Permisos Otorgados",
              cell: (r) => (
                <div style={{ display: "flex", flexWrap: "wrap", gap: "0.25rem" }}>
                  {r.permissions.map((p) => (
                    <span
                      key={p}
                      style={{
                        padding: "2px 6px",
                        backgroundColor: "var(--bg-input)",
                        borderRadius: "var(--radius-sm)",
                        fontFamily: "var(--font-mono)",
                        fontSize: "var(--text-2xs)",
                        color: "var(--text-secondary)",
                      }}
                    >
                      {p}
                    </span>
                  ))}
                </div>
              ),
            },
          ]}
          data={roles}
          keyExtractor={(r) => r.id}
          emptyTitle="Sin roles disponibles"
          emptyMessage="No se encontraron roles configurados en la organización."
        />
      </Card>

      {/* Role Creation Modal */}
      <Modal
        isOpen={isCreateOpen}
        onClose={() => setIsCreateOpen(false)}
        title="Crear Rol Personalizado"
        description="Defina el conjunto de permisos granulares permitidos para este rol"
      >
        <form onSubmit={handleCreateRole} style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          <Input
            label="Nombre del Rol"
            placeholder="AUDITOR_SEGURIDAD"
            value={newRoleName}
            onChange={(e) => setNewRoleName(e.target.value)}
            required
            autoFocus
          />

          <Input
            label="Descripción del Rol"
            placeholder="Acceso de solo lectura para auditoría y cumplimiento normativo"
            value={newRoleDescription}
            onChange={(e) => setNewRoleDescription(e.target.value)}
            required
          />

          <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
            <label style={{ fontSize: "var(--text-xs)", fontWeight: 600, color: "var(--text-secondary)" }}>
              Seleccione los Permisos Canónicos ({selectedPermissions.length} seleccionados)
            </label>
            <div
              style={{
                maxHeight: "220px",
                overflowY: "auto",
                display: "flex",
                flexDirection: "column",
                gap: "0.375rem",
                padding: "0.5rem",
                backgroundColor: "var(--bg-input)",
                border: "1px solid var(--border-default)",
                borderRadius: "var(--radius-md)",
              }}
            >
              {permissions.map((p) => {
                const checked = selectedPermissions.includes(p.code);
                return (
                  <label
                    key={p.code}
                    style={{
                      display: "flex",
                      alignItems: "flex-start",
                      gap: "0.5rem",
                      padding: "0.375rem",
                      backgroundColor: checked ? "var(--bg-surface)" : "transparent",
                      borderRadius: "var(--radius-sm)",
                      cursor: "pointer",
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => togglePermission(p.code)}
                      style={{ marginTop: "3px" }}
                    />
                    <div style={{ display: "flex", flexDirection: "column" }}>
                      <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--text-xs)", fontWeight: 600, color: "var(--text-primary)" }}>
                        {p.code} - {p.name}
                      </span>
                      <span style={{ fontSize: "var(--text-2xs)", color: "var(--text-muted)" }}>
                        {p.description}
                      </span>
                    </div>
                  </label>
                );
              })}
            </div>
          </div>

          <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem", marginTop: "1rem" }}>
            <Button type="button" variant="ghost" onClick={() => setIsCreateOpen(false)}>
              Cancelar
            </Button>
            <Button
              type="submit"
              variant="primary"
              isLoading={isCreating}
              disabled={!newRoleName.trim() || selectedPermissions.length === 0}
            >
              Crear Rol
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
