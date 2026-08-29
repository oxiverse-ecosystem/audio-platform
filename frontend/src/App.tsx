import React, { useEffect, useState } from "react";
import { api, type Asset, type Plan } from "./api";
import { Player, UsageBar } from "./Player";

interface Session {
  user_id: string;
  role: string;
  token: string;
}

function fmtPaise(p: number) {
  return `₹${(p / 100).toFixed(2)}`;
}

function AdminPanel({ token }: { token: string }) {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [period, setPeriod] = useState<string>(new Date().toISOString().slice(0, 7));
  const [payout, setPayout] = useState<any>(null);
  const [creator, setCreator] = useState({ id: "", asset: "", name: "" });
  const [msg, setMsg] = useState<string>("");

  const refreshPlans = () => { api.listPlans(token).then(setPlans).catch((e) => setMsg(e.message)); };
  useEffect(refreshPlans, [token]);

  async function savePlan(p: Plan) {
    await api.updatePlan(token, p.plan_code, {
      price_paise: p.price_paise,
      included_seconds: p.included_seconds,
      active: p.active,
    });
    setMsg(`Saved ${p.plan_code}`);
    refreshPlans();
  }

  async function runPayout() {
    const r = await api.computePayout(token, period);
    setPayout(r);
  }

  return (
    <div className="admin">
      <h2>Admin</h2>
      {msg && <div className="msg">{msg}</div>}

      <h3>Plans (editable — X/Y/Z live)</h3>
      <table>
        <thead>
          <tr><th>Code</th><th>Name</th><th>Price</th><th>Included (h)</th><th>Active</th><th></th></tr>
        </thead>
        <tbody>
          {plans.map((p) => (
            <tr key={p.plan_code}>
              <td>{p.plan_code}</td>
              <td>{p.name}</td>
              <td><input type="number" value={p.price_paise} onChange={(e) => setPlans(plans.map((x) => x.plan_code === p.plan_code ? { ...x, price_paise: +e.target.value } : x))} /></td>
              <td><input type="number" value={p.included_seconds ?? -1} onChange={(e) => setPlans(plans.map((x) => x.plan_code === p.plan_code ? { ...x, included_seconds: e.target.value === "-1" ? null : +e.target.value } : x))} /></td>
              <td><input type="checkbox" checked={!!p.active} onChange={(e) => setPlans(plans.map((x) => x.plan_code === p.plan_code ? { ...x, active: e.target.checked ? 1 : 0 } : x))} /></td>
              <td><button onClick={() => savePlan(p)}>Save</button></td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>Register creator</h3>
      <div className="row">
        <input placeholder="creator_id" value={creator.id} onChange={(e) => setCreator({ ...creator, id: e.target.value })} />
        <input placeholder="asset_id" value={creator.asset} onChange={(e) => setCreator({ ...creator, asset: e.target.value })} />
        <input placeholder="display name" value={creator.name} onChange={(e) => setCreator({ ...creator, name: e.target.value })} />
        <button onClick={async () => { await api.createCreator(token, creator.id, creator.asset, creator.name); setMsg("Creator created"); }}>Create</button>
      </div>

      <h3>Payouts</h3>
      <div className="row">
        <input value={period} onChange={(e) => setPeriod(e.target.value)} placeholder="YYYY-MM" />
        <button onClick={runPayout}>Compute payout</button>
      </div>
      {payout && (
        <div>
          <p>Gross {fmtPaise(payout.gross_paise)} → Net {fmtPaise(payout.net_paise)} · Pool {fmtPaise(payout.pool_paise)}</p>
          <table>
            <thead><tr><th>Creator</th><th>Source</th><th>Amount</th><th>Listeners</th><th>Seconds</th></tr></thead>
            <tbody>
              {payout.lines.map((l: any, i: number) => (
                <tr key={i}><td>{l.creator_id}</td><td>{l.source}</td><td>{fmtPaise(l.amount_paise)}</td><td>{l.unique_listeners}</td><td>{l.listened_seconds}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [selected, setSelected] = useState<Asset | null>(null);
  const [login, setLogin] = useState({ id: "demo-listener", role: "listener" as "listener" | "admin" });

  async function doLogin() {
    const r = await api.devLogin(login.id, login.role);
    setSession({ user_id: r.user_id, role: r.role, token: r.token });
    const a = await api.listAssets(r.token);
    setAssets(a.assets);
  }

  return (
    <div className="app">
      <header>
        <h1>Oxiverse Audio — Test Console</h1>
        {session && <span className="who">logged in as {session.user_id} ({session.role})</span>}
      </header>

      {!session ? (
        <div className="login">
          <input placeholder="user_id" value={login.id} onChange={(e) => setLogin({ ...login, id: e.target.value })} />
          <select value={login.role} onChange={(e) => setLogin({ ...login, role: e.target.value as any })}>
            <option value="listener">listener</option>
            <option value="admin">admin</option>
          </select>
          <button onClick={doLogin}>Dev login</button>
        </div>
      ) : (
        <div className="layout">
          <section className="catalog">
            <h2>Catalog</h2>
            {session.role === "listener" && <UsageBar token={session.token} />}
            {assets.length === 0 && <p className="empty">No assets yet. Upload via POST /v1/variant-assets (admin) or seed one.</p>}
            <ul>
              {assets.map((a) => (
                <li key={a.asset_id} className={selected?.asset_id === a.asset_id ? "active" : ""} onClick={() => setSelected(a)}>
                  <strong>{a.title}</strong>
                  <small>{a.creator_id || "unattributed"} · {Math.round(a.duration_seconds)}s · {a.segment_count} segs</small>
                </li>
              ))}
            </ul>
          </section>

          <section className="stage">
            {selected ? (
              <>
                <h2>{selected.title}</h2>
                <Player token={session.token} asset={selected} onUsageChange={() => {}} />
              </>
            ) : (
              <p className="empty">Select an asset to play.</p>
            )}
            {session.role === "admin" && <AdminPanel token={session.token} />}
          </section>
        </div>
      )}
    </div>
  );
}
