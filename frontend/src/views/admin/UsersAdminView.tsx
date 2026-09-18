import { useEffect, useState, useCallback } from "react";
import { adminApi } from "@/api/admin";
import type { UserSummaryResponse, RoleResponse } from "@/types/admin";
import { Table } from "@/components/common/Table";
import { Button } from "@/components/common/Button";
import { Badge } from "@/components/common/Badge";
import { Card } from "@/components/common/Card";
import { Modal } from "@/components/common/Modal";
import { Select } from "@/components/common/Select";
import { CreateUserModal } from "./CreateUserModal";
import { useNotification } from "@/context/NotificationContext";
import {
  RefreshCw,
  UserCheck,
  UserX,
  ShieldCheck,
  Plus,
  LogOut,
  Trash2,
  AlertTriangle,
} from "lucide-react";

export function UsersAdminView() {
  const { success, error: notifyError, info } = useNotification();
  const [users, setUsers] = useState<UserSummaryResponse[]>([]);
  const [roles, setRoles] = useState<RoleResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isCreateOpen, setIsCreateOpen] = useState(false);

  // Role Assignment Modal state
  const [assignTargetUser, setAssignTargetUser] = useState<UserSummaryResponse | null>(null);
  const [selectedRoleId, setSelectedRoleId] = useState("");
  const [isAssigning, setIsAssigning] = useState(false);

  // Delete User state
  const [deleteTargetUser, setDeleteTargetUser] = useState<UserSummaryResponse | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  const loadData = useCallback(async () => {
    setIsLoading(true);
    try {
      const [uList, rList] = await Promise.all([
        adminApi.listUsers({ limit: 100 }).catch(() => ({ items: [], next_cursor: null })),
        adminApi.listRoles().catch(() => ({ items: [] })),
      ]);
      setUsers(uList.items);
      setRoles(rList.items);
      if (rList.items.length > 0 && !selectedRoleId) {
        setSelectedRoleId(rList.items[0]?.id || "");
      }
    } catch (err: any) {
      notifyError("Error al cargar miembros de la organización", err.message);
    } finally {
      setIsLoading(false);
    }
  }, [notifyError, selectedRoleId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleAssignRole = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!assignTargetUser || !selectedRoleId) return;

    setIsAssigning(true);
    try {
      await adminApi.assignRole(selectedRoleId, assignTargetUser.id);
      success("Rol asignado exitosamente al colaborador", assignTargetUser.full_name);
      setAssignTargetUser(null);
      await loadData();
    } catch (err: any) {
      notifyError("Error al asignar rol", err.message);
    } finally {
      setIsAssigning(false);
    }
  };

  const handleToggleStatus = async (user: UserSummaryResponse) => {
    const nextStatus = !user.is_active;
    try {
      await adminApi.toggleUserStatus(user.id, nextStatus);
      success(
        nextStatus ? "Usuario Activado" : "Usuario Desactivado / Bloqueado",
        `El acceso de ${user.full_name} fue ${nextStatus ? "habilitado" : "bloqueado"}.`
      );
      await loadData();
    } catch (err: any) {
      notifyError("Error al actualizar estado del usuario", err.message);
    }
  };

  const handleRevokeSessions = async (user: UserSummaryResponse) => {
    try {
      const res = await adminApi.revokeUserSessions(user.id);
      info(
        "Sesiones Expulsadas",
        `Se han revocado las sesiones activas de ${user.full_name} (${res.revoked_sessions} sesión/es cerradas).`
      );
    } catch (err: any) {
      notifyError("Error al revocar sesiones", err.message);
    }
  };

  const handleDeleteUser = async () => {
    if (!deleteTargetUser) return;
    setIsDeleting(true);
    try {
      await adminApi.deleteUser(deleteTargetUser.id);
      success("Usuario Eliminado", `El usuario ${deleteTargetUser.full_name} fue removido de la organización.`);
      setDeleteTargetUser(null);
      await loadData();
    } catch (err: any) {
      notifyError("Error al eliminar usuario", err.message);
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
      {/* Action Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "0.75rem" }}>
        <p style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)" }}>
          Directorio de colaboradores, gestión de accesos, expulsión de sesiones y roles RBAC
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
            Registrar Usuario
          </Button>
        </div>
      </div>

      <Card>
        <Table
          columns={[
            {
              header: "Nombre Completo",
              cell: (u) => (
                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                  <div
                    style={{
                      width: "32px",
                      height: "32px",
                      borderRadius: "var(--radius-full)",
                      backgroundColor: "rgba(59, 130, 246, 0.15)",
                      color: "var(--brand-primary)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontWeight: 700,
                      fontSize: "12px",
                    }}
                  >
                    {u.full_name.charAt(0).toUpperCase()}
                  </div>
                  <div>
                    <div style={{ fontWeight: 600, color: "var(--text-primary)" }}>{u.full_name}</div>
                    <div style={{ fontSize: "var(--text-2xs)", color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
                      ID: {u.id.substring(0, 8)}...
                    </div>
                  </div>
                </div>
              ),
              width: "220px",
            },
            {
              header: "Correo Electrónico",
              cell: (u) => <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--text-xs)" }}>{u.email}</span>,
              width: "220px",
            },
            {
              header: "Estado",
              cell: (u) => (
                <Badge variant={u.is_active ? "healthy" : "offline"} dot>
                  {u.is_active ? "Activo" : "Inactivo / Bloqueado"}
                </Badge>
              ),
              width: "160px",
            },
            {
              header: "Acciones de Gestión",
              align: "right",
              width: "320px",
              cell: (u) => (
                <div style={{ display: "flex", gap: "0.375rem", justifyContent: "flex-end" }}>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => setAssignTargetUser(u)}
                    leftIcon={<ShieldCheck size={13} />}
                    title="Asignar rol de permisos"
                  >
                    Rol
                  </Button>

                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => handleRevokeSessions(u)}
                    leftIcon={<LogOut size={13} />}
                    title="Expulsar sesiones activas del usuario"
                  >
                    Expulsar
                  </Button>

                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleToggleStatus(u)}
                    title={u.is_active ? "Desactivar usuario" : "Activar usuario"}
                    style={{ color: u.is_active ? "var(--status-warning)" : "var(--status-healthy)" }}
                  >
                    {u.is_active ? <UserX size={14} /> : <UserCheck size={14} />}
                  </Button>

                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setDeleteTargetUser(u)}
                    title="Eliminar usuario de la organización"
                    style={{ color: "var(--status-critical)" }}
                  >
                    <Trash2 size={14} />
                  </Button>
                </div>
              ),
            },
          ]}
          data={users}
          keyExtractor={(u) => u.id}
          emptyTitle="Sin usuarios registrados"
          emptyMessage="No se encontraron usuarios en la organización."
        />
      </Card>

      {/* Create User Modal */}
      <CreateUserModal
        isOpen={isCreateOpen}
        onClose={() => setIsCreateOpen(false)}
        onCreated={() => loadData()}
      />

      {/* Role Assignment Modal */}
      {assignTargetUser && (
        <Modal
          isOpen={Boolean(assignTargetUser)}
          onClose={() => setAssignTargetUser(null)}
          title="Asignar Rol a Colaborador"
          description={`Usuario: ${assignTargetUser.full_name} (${assignTargetUser.email})`}
        >
          <form onSubmit={handleAssignRole} style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
            <Select
              label="Rol a Asignar"
              value={selectedRoleId}
              onChange={(e) => setSelectedRoleId(e.target.value)}
              options={roles.map((r) => ({
                value: r.id,
                label: `${r.name} ${r.is_system ? "(Sistema)" : "(Personalizado)"}`,
              }))}
            />

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem", marginTop: "1rem" }}>
              <Button type="button" variant="ghost" onClick={() => setAssignTargetUser(null)}>
                Cancelar
              </Button>
              <Button type="submit" variant="primary" isLoading={isAssigning} disabled={!selectedRoleId}>
                Confirmar Asignación
              </Button>
            </div>
          </form>
        </Modal>
      )}

      {/* Delete User Confirmation Modal */}
      {deleteTargetUser && (
        <Modal
          isOpen={Boolean(deleteTargetUser)}
          onClose={() => setDeleteTargetUser(null)}
          title="⚠️ Confirmar Eliminación de Usuario"
          maxWidth="460px"
        >
          <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", color: "var(--status-critical)" }}>
              <AlertTriangle size={24} />
              <div style={{ fontWeight: 600, fontSize: "var(--text-sm)" }}>
                ¿Estás seguro de eliminar a {deleteTargetUser.full_name}?
              </div>
            </div>
            <p style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)", lineHeight: 1.4 }}>
              Esta acción revocará inmediatamente todas sus sesiones activas y removerá su membresía de la organización <strong>{deleteTargetUser.email}</strong>.
            </p>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem", marginTop: "0.5rem" }}>
              <Button type="button" variant="secondary" onClick={() => setDeleteTargetUser(null)} disabled={isDeleting}>
                Cancelar
              </Button>
              <Button
                type="button"
                variant="primary"
                onClick={handleDeleteUser}
                isLoading={isDeleting}
                style={{ backgroundColor: "var(--status-critical)", borderColor: "var(--status-critical)" }}
              >
                Eliminar Usuario
              </Button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
