import { useState } from "react";
import { Modal } from "@/components/common/Modal";
import { Button } from "@/components/common/Button";
import { Input } from "@/components/common/Input";
import { Select } from "@/components/common/Select";
import { adminApi, type UserCreateInput } from "@/api/admin";
import { useNotification } from "@/context/NotificationContext";
import { UserPlus } from "lucide-react";

export interface CreateUserModalProps {
  isOpen: boolean;
  onClose: () => void;
  onCreated: () => void;
}

export function CreateUserModal({ isOpen, onClose, onCreated }: CreateUserModalProps) {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"ADMIN" | "TECHNICIAN" | "READER">("READER");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const { success, error: notifyError } = useNotification();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!fullName.trim() || !email.trim() || !password.trim()) return;

    setIsSubmitting(true);
    try {
      const payload: UserCreateInput = {
        full_name: fullName.trim(),
        email: email.trim().toLowerCase(),
        password: password.trim(),
        role,
      };

      await adminApi.createUser(payload);
      success("Usuario Registrado con Éxito", `Colaborador: ${fullName.trim()} (${email.trim()})`);
      setFullName("");
      setEmail("");
      setPassword("");
      setRole("READER");
      onCreated();
      onClose();
    } catch (err: any) {
      notifyError("Error al registrar usuario", err.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="👤 Registrar Nuevo Usuario en la Organización"
      maxWidth="500px"
    >
      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
        <p style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)", lineHeight: 1.4 }}>
          Crea un nuevo colaborador para asignarle acceso al Portal de Autoservicio o a la Consola de Administración Técnica.
        </p>

        <Input
          label="Nombre Completo"
          placeholder="Ej: Laura Martínez"
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
          required
        />

        <Input
          label="Correo Electrónico Corporativo"
          type="email"
          placeholder="laura@nexus.local"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />

        <Input
          label="Contraseña Inicial"
          type="password"
          placeholder="Mínimo 8 caracteres..."
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />

        <Select
          label="Rol de Acceso & Permisos"
          value={role}
          onChange={(e) => setRole(e.target.value as any)}
          options={[
            { value: "READER", label: "READER - Usuario de Portal (Acceso a su equipo y tickets)" },
            { value: "TECHNICIAN", label: "TECHNICIAN - Ingeniero de Soporte (Mesa de ayuda y telemetría)" },
            { value: "ADMIN", label: "ADMIN - Administrador Total (Control remoto, RBAC y auditoría)" },
          ]}
        />

        <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem", marginTop: "0.75rem" }}>
          <Button type="button" variant="secondary" onClick={onClose} disabled={isSubmitting}>
            Cancelar
          </Button>
          <Button
            type="submit"
            variant="primary"
            isLoading={isSubmitting}
            leftIcon={<UserPlus size={14} />}
          >
            Registrar Usuario
          </Button>
        </div>
      </form>
    </Modal>
  );
}
