import { useEffect, useRef, useState, useCallback } from "react";

export type WebSocketStatus = "CONNECTING" | "CONNECTED" | "DISCONNECTED" | "ERROR";

export interface RealtimeEvent<T = unknown> {
  type: "telemetry" | "alert" | "device_status" | "ready" | "pong";
  payload?: T;
  [key: string]: unknown;
}

export interface UseWebSocketOptions {
  enabled?: boolean;
  onEvent?: (event: RealtimeEvent) => void;
  maxReconnectAttempts?: number;
}

export function useWebSocket(options: UseWebSocketOptions = {}) {
  const { enabled = true, onEvent, maxReconnectAttempts = 15 } = options;
  const [status, setStatus] = useState<WebSocketStatus>("DISCONNECTED");
  const [lastEvent, setLastEvent] = useState<RealtimeEvent | null>(null);
  const [isManualPaused, setIsManualPaused] = useState(false);

  const socketRef = useRef<WebSocket | null>(null);
  const reconnectAttempts = useRef(0);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (socketRef.current) {
      socketRef.current.onclose = null;
      socketRef.current.onerror = null;
      socketRef.current.onmessage = null;
      socketRef.current.onopen = null;
      socketRef.current.close();
      socketRef.current = null;
    }
    setStatus("DISCONNECTED");
  }, []);

  const connect = useCallback(() => {
    if (!enabled || isManualPaused || typeof window === "undefined") return;

    if (socketRef.current) {
      disconnect();
    }

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    const wsUrl = `${protocol}//${host}/api/v1/ws/telemetry`;

    setStatus("CONNECTING");

    try {
      const ws = new WebSocket(wsUrl);
      socketRef.current = ws;

      ws.onopen = () => {
        setStatus("CONNECTED");
        reconnectAttempts.current = 0;
      };

      ws.onmessage = (messageEvent) => {
        try {
          const parsed = JSON.parse(messageEvent.data) as RealtimeEvent;
          setLastEvent(parsed);
          if (onEventRef.current) {
            onEventRef.current(parsed);
          }
        } catch {
          // ignore non-json ping/pong frames
        }
      };

      ws.onerror = () => {
        setStatus("ERROR");
      };

      ws.onclose = () => {
        setStatus("DISCONNECTED");
        socketRef.current = null;

        if (enabled && !isManualPaused && reconnectAttempts.current < maxReconnectAttempts) {
          reconnectAttempts.current += 1;
          const baseDelay = Math.min(1000 * Math.pow(1.4, reconnectAttempts.current), 15000);
          const jitter = Math.random() * 500;
          const delay = baseDelay + jitter;

          reconnectTimeoutRef.current = window.setTimeout(() => {
            connect();
          }, delay);
        }
      };
    } catch {
      setStatus("ERROR");
    }
  }, [enabled, isManualPaused, maxReconnectAttempts, disconnect]);

  const toggleConnection = useCallback(() => {
    setIsManualPaused((prev) => {
      const next = !prev;
      if (next) {
        disconnect();
      }
      return next;
    });
  }, [disconnect]);

  const send = useCallback((data: unknown) => {
    if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
      socketRef.current.send(typeof data === "string" ? data : JSON.stringify(data));
      return true;
    }
    return false;
  }, []);

  useEffect(() => {
    if (enabled && !isManualPaused) {
      connect();
    } else {
      disconnect();
    }
    return () => {
      disconnect();
    };
  }, [enabled, isManualPaused, connect, disconnect]);

  return {
    status: isManualPaused ? "DISCONNECTED" : status,
    lastEvent,
    isManualPaused,
    toggleConnection,
    send,
    reconnect: connect,
  };
}
