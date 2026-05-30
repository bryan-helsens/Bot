import { useEffect, useRef, useState } from "react";
import type { WsMessage } from "../types";

// Subscribe to the backend's WebSocket push stream with auto-reconnect.
// Returns the latest message and a connection flag; the caller reacts to
// messages to refresh the relevant data.
export function useWebSocket(): { lastMessage: WsMessage | null; connected: boolean } {
  const [lastMessage, setLastMessage] = useState<WsMessage | null>(null);
  const [connected, setConnected] = useState(false);
  const reconnectRef = useRef<number | null>(null);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let closed = false;
    let delay = 1000;

    const connect = () => {
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(`${proto}://${window.location.host}/ws`);

      socket.onopen = () => {
        setConnected(true);
        delay = 1000;
      };
      socket.onmessage = (event) => {
        try {
          setLastMessage(JSON.parse(event.data) as WsMessage);
        } catch {
          /* ignore malformed frames */
        }
      };
      socket.onclose = () => {
        setConnected(false);
        if (!closed) {
          reconnectRef.current = window.setTimeout(connect, delay);
          delay = Math.min(delay * 2, 30000);
        }
      };
      socket.onerror = () => socket?.close();
    };

    connect();
    return () => {
      closed = true;
      if (reconnectRef.current) window.clearTimeout(reconnectRef.current);
      socket?.close();
    };
  }, []);

  return { lastMessage, connected };
}
