import { useState } from "react";
import { api } from "../api/client";
import { cls, money, signedMoney } from "../format";
import { usePolling } from "../hooks/usePolling";
import type { TaxReport } from "../types";

async function downloadCsv() {
  const token = localStorage.getItem("qb_token");
  const resp = await fetch("/api/tax/trades.csv", {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!resp.ok) return;
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "quantbot_trades.csv";
  a.click();
  URL.revokeObjectURL(url);
}

/** Fiscaal overzicht: de gerealiseerde cijfers per jaar die je aangifte nodig heeft. */
export function TaxPage() {
  const { data } = usePolling<TaxReport>(() => api.taxReport(), 30000);
  const [busy, setBusy] = useState(false);

  if (!data) {
    return (
      <div className="panel">
        <h2>Belasting / Fiscaal</h2>
        <div className="empty">Loading…</div>
      </div>
    );
  }

  return (
    <>
      {data.is_testnet && (
        <div className="panel">
          <div className="note ok">
            🧪 <b>Testnet (nepgeld)</b> — er is geen echte winst, dus <b>niets aan te geven</b>.
            Deze pagina toont vast welke cijfers je nodig hebt zodra je met echt geld handelt.
          </div>
        </div>
      )}

      <div className="panel">
        <h2>Gerealiseerd resultaat per jaar (in {data.quote_asset})</h2>
        {data.years.length === 0 ? (
          <div className="empty">Nog geen gesloten trades.</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Jaar</th>
                <th>Trades (W/V)</th>
                <th>Gerealiseerde winst/verlies</th>
                <th>Fees</th>
                <th>Kapitaal gestort</th>
              </tr>
            </thead>
            <tbody>
              {data.years.map((y) => (
                <tr key={y.year}>
                  <td>{y.year}</td>
                  <td>
                    {y.trades} <span className="muted">({y.wins}/{y.losses})</span>
                  </td>
                  <td className={cls(y.realized_pnl)}>{signedMoney(y.realized_pnl)}</td>
                  <td className="muted">{money(y.fees)}</td>
                  <td className="muted">{money(y.capital_added)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="controls-row" style={{ marginTop: 10 }}>
          <button
            className="btn-buy"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await downloadCsv();
              } finally {
                setBusy(false);
              }
            }}
          >
            ⬇️ Download trade-overzicht (CSV)
          </button>
        </div>
        <p className="hint">
          De CSV bevat per trade: aankoop-/verkoopdatum, hoeveelheid, kostprijs, opbrengst,
          fees en winst — precies wat je boekhouder nodig heeft.
        </p>
      </div>

      <div className="panel">
        <h2>Wat moet je aangeven? (België)</h2>
        <table>
          <tbody>
            <tr>
              <th>Regime</th>
              <td>{data.notes.regime}</td>
            </tr>
            <tr>
              <th>Winst aangeven</th>
              <td>{data.notes.declare}</td>
            </tr>
            <tr>
              <th>Buitenlandse rekening</th>
              <td>{data.notes.foreign_account}</td>
            </tr>
            <tr>
              <th>Testnet</th>
              <td>{data.notes.testnet}</td>
            </tr>
          </tbody>
        </table>
        <div className="note err" style={{ marginTop: 10 }}>
          ⚠️ {data.notes.disclaimer} Belgische crypto-belasting is complex en net gewijzigd
          (2026): laat je bij echt geld bijstaan door een fiscalist of vraag een ruling aan.
        </div>
      </div>
    </>
  );
}
