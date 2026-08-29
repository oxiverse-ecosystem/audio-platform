// Thin API client for the audio service. All calls go through the Vite dev proxy to :8000.
const BASE = "";

export interface Plan {
  plan_code: string;
  name: string;
  kind: string;
  price_paise: number;
  included_seconds: number | null;
  active: number;
}

export interface Asset {
  asset_id: string;
  title: string;
  creator_id: string | null;
  duration_seconds: number;
  segment_count: number;
}

export interface Usage {
  user_id: string;
  consumed_seconds: number;
  included_seconds: number | null;
  remaining_seconds: number | null;
}

async function req(path: string, opts: RequestInit = {}): Promise<any> {
  const res = await fetch(BASE + path, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(opts.headers || {}),
    },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return res.status === 204 ? null : res.json();
}

export const api = {
  devLogin: (userId: string, role: "listener" | "admin" = "listener") =>
    req("/v1/dev-login", { method: "POST", body: JSON.stringify({ user_id: userId, role }) }),

  listAssets: (token: string) => req("/v1/assets", { headers: { Authorization: `Bearer ${token}` } }),

  createSession: (token: string, assetId: string) =>
    req("/v1/variant-streams", {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify({ asset_id: assetId }),
    }),

  getUsage: (token: string) => req("/v1/usage", { headers: { Authorization: `Bearer ${token}` } }),

  listPlans: (token: string) => req("/v1/plans", { headers: { Authorization: `Bearer ${token}` } }),

  updatePlan: (token: string, planCode: string, body: Partial<Plan>) =>
    req(`/v1/plans/${planCode}`, {
      method: "PUT",
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify(body),
    }),

  createCreator: (token: string, creatorId: string, assetId: string, displayName: string) =>
    req("/v1/creators", {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify({ creator_id: creatorId, asset_id: assetId, display_name: displayName }),
    }),

  computePayout: (token: string, period: string) =>
    req(`/v1/payouts/compute?period=${period}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    }),
};
