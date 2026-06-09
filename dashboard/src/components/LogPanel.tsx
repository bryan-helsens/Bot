import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { usePolling } from "../hooks/usePolling";
import type { LogEntry } from "../types";

const LEVEL_CLASS: Record<string, string> = {
  CRITICAL: "log-critical",
  ERROR: "log-error",
  WARNING: "log-warning",
  INFO: "log-info",
  DEBUG: "log-debug",
};

/** Live log feed — shows what the bot is doing, newest at the bottom. */
export function LogPanel() {
  const { data } = usePolling<LogEntry[]>(() => api.logs(200), 2000);
  const [autoscroll, setAutoscroll] = useState(true);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (autoscroll && boxRef.current) {
      boxRef.current.scrollTop = boxRef.current.scrollHeight;
    }
  }, [data, autoscroll]);

  return (
    <div className="panel">
      <div className="log-head">
        <h2>Logs</h2>
        <label className="log-toggle">
          <input
            type="checkbox"
            checked={autoscroll}
            onChange={(e) => setAutoscroll(e.target.checked)}
          />
          auto-scroll
        </label>
      </div>
      <div className="log-box" ref={boxRef}>
        {!data || data.length === 0 ? (
          <div className="empty">No logs yet.</div>
        ) : (
          data.map((l, i) => {
            const time = l.ts ? l.ts.slice(11, 19) : "";
            const ctx = Object.entries(l.data)
              .filter(([k]) => k !== "stack")
              .map(([k, v]) => `${k}=${v}`)
              .join(" ");
            return (
              <div key={i} className={`log-line ${LEVEL_CLASS[l.level.toUpperCase()] ?? ""}`}>
                <span className="log-time">{time}</span>
                <span className="log-level">{l.level.toUpperCase().slice(0, 4)}</span>
                <span className="log-event">{l.event}</span>
                {ctx && <span className="log-ctx"> {ctx}</span>}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
