import { useState, useRef, useEffect } from "react";
import { Button } from "@/components/common/Button";
import { Terminal, Send, Trash2, Shield } from "lucide-react";

export interface WebTerminalViewProps {
  deviceId: string;
  hostname: string;
  isOnline: boolean;
}

interface CommandLog {
  id: string;
  command: string;
  output: string;
  timestamp: string;
  isError?: boolean;
}

const DEMO_COMMAND_OUTPUTS: Record<string, string> = {
  help: `Comandos disponibles en esta demostración local:
  • systeminfo    - Información detallada del sistema operativo y hardware
  • top           - Lista de procesos y consumo de recursos
  • ipconfig      - Configuración de adaptadores de red y direcciones IP
  • ping          - Prueba de conectividad ICMP hacia la puerta de enlace
  • netstat       - Puertos y conexiones TCP/UDP activas
  • uptime        - Tiempo de actividad continuo del sistema
  • diskpart      - Estado de particiones y volúmenes de almacenamiento
  • clear         - Limpiar la pantalla de la terminal`,

  systeminfo: `Host Name:                 %HOSTNAME%
OS Name:                   Linux / Windows Server Enterprise
OS Version:                6.18.33.2-microsoft-standard-WSL2
System Manufacturer:       Nexus Monitored Workstation
System Model:              Virtual Hardware x64
Total Physical Memory:     16,384 MB
Available Physical Memory:  8,412 MB
Page File Space: Available: 4,096 MB
Hotfix(es):                12 Hotfix(es) Installed
Network Cards:             1 NIC(s) Installed [01]: eth0 (172.19.0.1)`,

  top: `PID   USER      PR  NI    VIRT    RES    SHR S  %CPU  %MEM     TIME+ COMMAND
 1042 root      20   0  712400  48212  14200 S   3.2   1.4   0:14.22 nexus-agent
  842 postgres  20   0  480200 120400  98200 S   1.8   3.7   1:02.10 postgres: writer
  312 system    20   0  120400  18200  12400 S   0.5   0.6   0:04.18 systemd-journal
 1289 redis     20   0   48200  14100   8200 S   0.2   0.4   0:01.42 redis-server`,

  ipconfig: `Configuración IP de Adaptadores:
Adaptador Ethernet eth0:
   Sufijo DNS específico para la conexión. . : localdomain
   Vínculo: dirección IPv6 local. . . . . . . : fe80::5054:ff:fe12:3456%3
   Dirección IPv4. . . . . . . . . . . . . . : 172.19.0.15
   Máscara de subred . . . . . . . . . . . . : 255.255.0.0
   Puerta de enlace predeterminada . . . . . : 172.19.0.1`,

  ping: `Haciendo ping a 172.19.0.1 con 32 bytes de datos:
Respuesta desde 172.19.0.1: bytes=32 tiempo=1.2ms TTL=64
Respuesta desde 172.19.0.1: bytes=32 tiempo=0.9ms TTL=64
Respuesta desde 172.19.0.1: bytes=32 tiempo=1.1ms TTL=64
Respuesta desde 172.19.0.1: bytes=32 tiempo=0.8ms TTL=64

Estadísticas de ping para 172.19.0.1:
    Paquetes: enviados = 4, recibidos = 4, perdidos = 0 (0% perdidos).`,

  netstat: `Conexiones activas:
  Proto  Dirección local          Dirección remota        Estado
  TCP    127.0.0.1:8000           127.0.0.1:5432          ESTABLISHED
  TCP    172.19.0.15:443          142.250.190.46:443      ESTABLISHED
  TCP    127.0.0.1:6379           127.0.0.1:45120         ESTABLISHED`,

  uptime: `Sistema operativo activo durante: 14 días, 6 horas, 42 minutos.
Carga promedio: 0.12, 0.18, 0.15`,

  diskpart: `Volumen ###  Ltr  Etiqueta     Fs     Tipo        Tamaño   Estado     Info
----------  ---  -----------  -----  ----------  -------  ---------  --------
Volumen 0    C   SISTEMA      NTFS   Partición    476 GB  Correcto   Sistema
Volumen 1    D   DATOS        NTFS   Partición    931 GB  Correcto   `,
};

export function WebTerminalView({ hostname, isOnline }: WebTerminalViewProps) {
  const [inputCommand, setInputCommand] = useState("");
  const [logs, setLogs] = useState<CommandLog[]>([
    {
      id: "init",
      command: "connect",
      output: `[DEMO] Vista previa local de diagnóstico para ${hostname}.
[DEMO] No existe conexión con el agente y ningún comando se ejecuta.
[DEMO] Escribe 'help' para ver las salidas simuladas disponibles.`,
      timestamp: new Date().toLocaleTimeString(),
    },
  ]);

  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (typeof bottomRef.current?.scrollIntoView === "function") {
      bottomRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs]);

  const handleExecute = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const trimmed = inputCommand.trim().toLowerCase();
    if (!trimmed) return;

    if (trimmed === "clear") {
      setLogs([]);
      setInputCommand("");
      return;
    }

    let output = "";
    let isError = false;

    if (DEMO_COMMAND_OUTPUTS[trimmed]) {
      output = `[SALIDA SIMULADA]\n${DEMO_COMMAND_OUTPUTS[trimmed].replace("%HOSTNAME%", hostname)}`;
    } else {
      isError = true;
      output = `Demostración: entrada no reconocida: '${trimmed}'.\nNo se envió ni ejecutó ningún comando. Escribe 'help' para consultar las salidas simuladas.`;
    }

    const newLog: CommandLog = {
      id: Math.random().toString(36).substring(2, 9),
      command: inputCommand.trim(),
      output,
      timestamp: new Date().toLocaleTimeString(),
      isError,
    };

    setLogs((prev) => [...prev, newLog]);
    setInputCommand("");
  };

  const handleQuickCmd = (cmd: string) => {
    setInputCommand(cmd);
  };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "0.75rem",
        backgroundColor: "#080b11",
        borderRadius: "var(--radius-xl)",
        border: "1px solid rgba(255, 255, 255, 0.08)",
        padding: "1rem",
      }}
    >
      {/* Terminal Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: "0.5rem",
          paddingBottom: "0.75rem",
          borderBottom: "1px solid rgba(255,255,255,0.06)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <Terminal size={18} color="var(--status-healthy)" />
          <span style={{ fontSize: "var(--text-sm)", fontWeight: 700 }}>
            Vista previa de diagnóstico: {hostname}
          </span>
          <span
            style={{
              fontSize: "var(--text-2xs)",
              padding: "0.15rem 0.5rem",
              borderRadius: "var(--radius-full)",
              backgroundColor: isOnline ? "rgba(16, 185, 129, 0.1)" : "rgba(255,255,255,0.05)",
              color: isOnline ? "var(--status-healthy)" : "var(--text-muted)",
              border: isOnline ? "1px solid rgba(16, 185, 129, 0.3)" : "1px solid rgba(255,255,255,0.1)",
            }}
          >
            {isOnline ? "Simulación disponible" : "Equipo desconectado"}
          </span>
        </div>

        {/* Quick Diagnostic Shortcuts */}
        <div style={{ display: "flex", alignItems: "center", gap: "0.375rem", flexWrap: "wrap" }}>
          <span style={{ fontSize: "var(--text-2xs)", color: "var(--text-muted)" }}>Rápidos:</span>
          {["systeminfo", "top", "ping", "uptime"].map((cmd) => (
            <button
              key={cmd}
              onClick={() => handleQuickCmd(cmd)}
              style={{
                fontSize: "var(--text-2xs)",
                fontFamily: "var(--font-mono)",
                padding: "0.2rem 0.5rem",
                borderRadius: "var(--radius-sm)",
                backgroundColor: "#131823",
                color: "var(--brand-primary)",
                border: "1px solid rgba(255,255,255,0.1)",
                cursor: "pointer",
              }}
            >
              {cmd}
            </button>
          ))}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setLogs([])}
            leftIcon={<Trash2 size={12} />}
            title="Limpiar pantalla"
          />
        </div>
      </div>

      {/* Terminal Output Screen */}
      <div
        style={{
          height: "360px",
          backgroundColor: "#030407",
          borderRadius: "var(--radius-lg)",
          padding: "1rem",
          overflowY: "auto",
          fontFamily: "var(--font-mono)",
          fontSize: "var(--text-xs)",
          lineHeight: 1.5,
          color: "#58a6ff",
          border: "1px solid rgba(255,255,255,0.05)",
          display: "flex",
          flexDirection: "column",
          gap: "0.75rem",
        }}
      >
        {logs.map((log) => (
          <div key={log.id} style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", color: "#8b949e" }}>
              <span style={{ color: "#238636" }}>nexus@{hostname.toLowerCase()}</span>
              <span style={{ color: "#8b949e" }}>:</span>
              <span style={{ color: "#388bfd" }}>~</span>
              <span style={{ color: "#f0f6fc" }}>$ {log.command}</span>
              <span style={{ marginLeft: "auto", fontSize: "10px", color: "#484f58" }}>{log.timestamp}</span>
            </div>
            <pre
              style={{
                margin: 0,
                color: log.isError ? "var(--status-critical)" : "#c9d1d9",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                fontFamily: "inherit",
              }}
            >
              {log.output}
            </pre>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Terminal Input Form */}
      <form
        onSubmit={handleExecute}
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.5rem",
          backgroundColor: "#0d1117",
          borderRadius: "var(--radius-md)",
          padding: "0.375rem 0.75rem",
          border: "1px solid rgba(255,255,255,0.1)",
        }}
      >
        <span style={{ color: "#238636", fontFamily: "var(--font-mono)", fontSize: "var(--text-xs)", fontWeight: 700 }}>
          $
        </span>
        <input
          type="text"
          value={inputCommand}
          onChange={(e) => setInputCommand(e.target.value)}
          placeholder="Prueba una salida simulada: 'systeminfo', 'top', 'ping' o 'help'..."
          disabled={!isOnline}
          style={{
            flex: 1,
            backgroundColor: "transparent",
            border: "none",
            outline: "none",
            color: "#f0f6fc",
            fontFamily: "var(--font-mono)",
            fontSize: "var(--text-xs)",
          }}
        />
        <Button
          type="submit"
          variant="primary"
          size="sm"
          disabled={!isOnline || !inputCommand.trim()}
          leftIcon={<Send size={12} />}
        >
          Simular
        </Button>
      </form>

      {/* Security Footer */}
      <div style={{ display: "flex", alignItems: "center", gap: "0.375rem", fontSize: "var(--text-2xs)", color: "var(--text-muted)", padding: "0 0.25rem" }}>
        <Shield size={12} color="var(--status-healthy)" />
        <span>Prototipo local: no conecta con el agente, no ejecuta comandos y no genera auditoría real</span>
      </div>
    </div>
  );
}
