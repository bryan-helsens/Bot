import { useState } from "react";
import { api } from "../api/client";
import { cls, money, price, signedMoney } from "../format";
import type { Position } from "../types";

export function OpenPositions({ positions }: { positions: Position[] }) {
  const [busy, setBusy] = useState<string | null>(null);

  async function close(symbol: string) {
    setBusy(symbol);
    try {
      await api.closePosition(symbol);
    } catch {
      /* errors surface in the Activity/Logs panels */
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="panel">
      <h2>Open Positions ({positions.length})</h2>
      {positions.length === 0 ? (
        <div className="empty">No open positions.</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Side</th>
              <th>Qty</th>
              <th>Entry</th>
              <th>Mark</th>
              <th>Value</th>
              <th>uPnL</th>
              <th>Stop</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => (
              <tr key={p.id}>
                <td>{p.symbol}</td>
                <td className={p.side === "long" ? "pos" : "neg"}>{p.side}</td>
                <td>{parseFloat(p.quantity).toFixed(4)}</td>
                <td>{price(p.entry_price)}</td>
                <td>{p.mark_price ? price(p.mark_price) : "—"}</td>
                <td>
                  {p.mark_price
                    ? money(parseFloat(p.quantity) * parseFloat(p.mark_price))
                    : "—"}
                </td>
                <td className={cls(p.unrealized_pnl)}>{signedMoney(p.unrealized_pnl)}</td>
                <td>{p.stop_loss ? price(p.stop_loss) : "—"}</td>
                <td>
                  <button
                    className="btn-sell btn-sm"
                    disabled={busy === p.symbol}
                    onClick={() => close(p.symbol)}
                  >
                    Close
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
