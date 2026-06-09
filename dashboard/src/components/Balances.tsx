import type { Portfolio, Position } from "../types";

/**
 * Clear money breakdown: how much is in free cash vs. held in each coin (valued at
 * the current mark price), plus the total. Values are in the quote currency (USDT).
 */
export function Balances({
  portfolio,
  positions,
}: {
  portfolio: Portfolio | null;
  positions: Position[];
}) {
  const cash = portfolio ? parseFloat(portfolio.cash) : 0;
  const equity = portfolio ? parseFloat(portfolio.equity) : 0;
  const pct = (v: number) => (equity > 0 ? (v / equity) * 100 : 0);

  const rows = positions
    .map((p) => {
      const qty = parseFloat(p.quantity);
      const mark = p.mark_price ? parseFloat(p.mark_price) : parseFloat(p.entry_price);
      const value = qty * mark;
      return { symbol: p.symbol, qty, value, upnl: parseFloat(p.unrealized_pnl) };
    })
    .sort((a, b) => b.value - a.value);

  const fmt = (n: number) =>
    n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  return (
    <div className="panel">
      <h2>Balances (USDT)</h2>
      <table>
        <thead>
          <tr>
            <th>Asset</th>
            <th style={{ textAlign: "right" }}>Value</th>
            <th style={{ textAlign: "right" }}>% equity</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <th>💵 Free cash</th>
            <td style={{ textAlign: "right" }}>{fmt(cash)}</td>
            <td style={{ textAlign: "right" }}>{pct(cash).toFixed(1)}%</td>
          </tr>
          {rows.map((r) => (
            <tr key={r.symbol}>
              <th>
                {r.symbol}{" "}
                <span className="muted" style={{ fontWeight: 400 }}>
                  ({r.qty.toLocaleString(undefined, { maximumFractionDigits: 6 })})
                </span>
              </th>
              <td style={{ textAlign: "right" }}>
                {fmt(r.value)}{" "}
                <span className={r.upnl > 0 ? "pos" : r.upnl < 0 ? "neg" : ""}>
                  ({r.upnl >= 0 ? "+" : ""}
                  {fmt(r.upnl)})
                </span>
              </td>
              <td style={{ textAlign: "right" }}>{pct(r.value).toFixed(1)}%</td>
            </tr>
          ))}
          <tr className="total">
            <th>Total equity</th>
            <td style={{ textAlign: "right" }}>
              <strong>{fmt(equity)}</strong>
            </td>
            <td style={{ textAlign: "right" }}>100%</td>
          </tr>
        </tbody>
      </table>
      <p className="hint">
        Values are in USDT (the quote currency). "(±x)" next to a coin is its
        unrealised PnL.
      </p>
    </div>
  );
}
