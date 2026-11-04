import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { AdminConditions, type ConditionCatalog, type ExtraCondition } from "./AdminConditions";
import { RangePicker, browserZone, defaultRange, fmtWindow, isoDay, pct, rangeQuery, rangeValid, type Range } from "./AdminKit";
import { AdminOverview, type DiscordState } from "./AdminOverview";
import { AdminPreview } from "./AdminPreview";
import { AdminRecap } from "./AdminRecap";
import { AdminResults, type ResultsInsights, type StrategyMeta } from "./AdminResults";
import { AdminTips } from "./AdminTips";
import { AdminVisitors } from "./AdminVisitors";

type WeightRow = {
  key: string;
  label: string;
  default: number;
  current: number;
  min: number;
  max: number;
  step: number;
  description: string;
  suggested?: string;
};

type StrategyConfig = {
  slot: number;
  key: string;
  name: string;
  short: string;
  equation: string;
  blurb: string;
  threshold: number;
  cooldown_minutes: number;
  cooldown_bypass_delta: number | null;
  max_fire_minute: number | null;
  max_fire_minute_1h: number | null;
  enabled: boolean;
  success_window_minutes: number;
  expiration_buffer_minutes: number;
  infinite_ttl: boolean;
  team_specific: boolean;
  expire_at_half_end: boolean;
  weights: WeightRow[];
  presets: string[];
  saved_presets: string[];
  conditions: ExtraCondition[];
};

type SweetSpotConfig = {
  ht1_start: number;
  ht1_end: number;
  ht2_start: number;
  ht2_end: number;
  include_injury_time: boolean;
};

const DEFAULT_SWEET_SPOT: SweetSpotConfig = {
  ht1_start: 28,
  ht1_end: 44,
  ht2_start: 72,
  ht2_end: 88,
  include_injury_time: false,
};

const DEFAULT_DISCORD: DiscordState = {
  free_channel_id: null,
  paid_channel_id: null,
  free_enabled: true,
  paid_enabled: true,
};

type Page = "overview" | "results" | "visitors" | "strategies" | "board" | "recap" | "tips" | "discord";

const PAGES: Record<Page, { group: string; title: string }> = {
  overview: { group: "Today", title: "Overview" },
  results: { group: "Insights", title: "Results" },
  visitors: { group: "Insights", title: "Visitors" },
  strategies: { group: "Strategy", title: "Strategies" },
  board: { group: "Strategy", title: "Board filters" },
  recap: { group: "Distribution", title: "Recaps" },
  tips: { group: "Distribution", title: "Tips feed" },
  discord: { group: "Distribution", title: "Discord" },
};

// The fields each save endpoint owns; anything here that differs from what
// was loaded counts as an unsaved change.
const SETTING_FIELDS = [
  "threshold",
  "cooldown_minutes",
  "cooldown_bypass_delta",
  "max_fire_minute",
  "max_fire_minute_1h",
  "enabled",
  "success_window_minutes",
  "expiration_buffer_minutes",
  "infinite_ttl",
  "team_specific",
  "expire_at_half_end",
] as const;

type SettingField = (typeof SETTING_FIELDS)[number];
type SettingSnapshot = Record<number, Pick<StrategyConfig, SettingField>>;

function snapshot(rows: StrategyConfig[]): SettingSnapshot {
  return Object.fromEntries(
    rows.map((row) => [row.slot, Object.fromEntries(SETTING_FIELDS.map((f) => [f, row[f]]))]),
  ) as SettingSnapshot;
}

function pageFromHash(): Page {
  const raw = window.location.hash.replace(/^#/, "").split(":")[0];
  return raw in PAGES ? (raw as Page) : "overview";
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  const body = (await res.json().catch(() => ({}))) as T & { detail?: string };
  if (!res.ok) {
    const detail = typeof body.detail === "string" ? body.detail : `HTTP ${res.status}`;
    throw new Error(detail);
  }
  return body;
}

const ICONS: Record<Page, ReactNode> = {
  overview: (
    <>
      <rect x="2" y="2" width="5" height="5" rx="1" />
      <rect x="9" y="2" width="5" height="5" rx="1" />
      <rect x="2" y="9" width="5" height="5" rx="1" />
      <rect x="9" y="9" width="5" height="5" rx="1" />
    </>
  ),
  results: <path d="M2 13l4-5 3 3 5-7" />,
  visitors: (
    <>
      <circle cx="6" cy="5.5" r="2.5" />
      <path d="M1.5 14c.6-2.6 2.3-4 4.5-4s3.9 1.4 4.5 4M11 3.2a2.4 2.4 0 010 4.6M12.5 10.3c1.1.6 1.8 1.8 2 3.7" />
    </>
  ),
  strategies: <path d="M3 4h10M3 8h10M3 12h10M6 2.6v2.8M10 6.6v2.8M5 10.6v2.8" />,
  board: (
    <>
      <rect x="2" y="3" width="12" height="10" rx="1.5" />
      <path d="M2 6.5h12M6 6.5V13" />
    </>
  ),
  tips: <path d="M3 3h10v7H7l-3 3v-3H3z" />,
  discord: <path d="M2 8h3l2-5 2 10 2-5h3" />,
  recap: (
    <>
      <rect x="2.5" y="2.5" width="11" height="11" rx="1.5" />
      <path d="M5 10.5V8M8 10.5V5.5M11 10.5V7" />
    </>
  ),
};

function NavItem({ page, on, onClick, badge }: { page: Page; on: boolean; onClick: () => void; badge?: ReactNode }) {
  return (
    <button type="button" className={`adm-nav-item ${on ? "is-on" : ""}`} onClick={onClick}>
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
        {ICONS[page]}
      </svg>
      {PAGES[page].title}
      {badge ? <span className="adm-nav-badge">{badge}</span> : null}
    </button>
  );
}

export function AdminApp() {
  const zone = useMemo(browserZone, []);
  const [configured, setConfigured] = useState(true);
  const [authed, setAuthed] = useState(false);
  const [password, setPassword] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState<Page>(pageFromHash);
  const [items, setItems] = useState<StrategyConfig[]>([]);
  const [saved, setSaved] = useState<SettingSnapshot>({});
  const [strategyKey, setStrategyKey] = useState("rule_of_three");
  const [resultStrategy, setResultStrategy] = useState<string | null>(null);
  const [range, setRange] = useState<Range>(() => defaultRange("1"));
  const [presetName, setPresetName] = useState("");
  const [busy, setBusy] = useState(false);
  const [various, setVarious] = useState<SweetSpotConfig>(DEFAULT_SWEET_SPOT);
  const [savedVarious, setSavedVarious] = useState<SweetSpotConfig>(DEFAULT_SWEET_SPOT);
  const [discord, setDiscord] = useState<DiscordState>(DEFAULT_DISCORD);
  const [savedDiscord, setSavedDiscord] = useState<DiscordState>(DEFAULT_DISCORD);
  const [catalog, setCatalog] = useState<ConditionCatalog>({
    scopes: [],
    metrics: [],
    operators: [">=", ">", "<", "<=", "="],
  });
  const condTimer = useRef(0);

  const load = useCallback(async () => {
    const session = await api<{ ok: boolean; configured: boolean }>("/api/admin/session");
    setConfigured(session.configured);
    if (!session.ok) {
      setAuthed(false);
      return;
    }
    setAuthed(true);
    const cfg = await api<{
      strategies: StrategyConfig[];
      various?: SweetSpotConfig;
      discord?: DiscordState;
      condition_catalog?: ConditionCatalog;
    }>("/api/admin/config");
    const rows = cfg.strategies.map((row) => ({ ...row, conditions: row.conditions || [] }));
    setItems(rows);
    setSaved(snapshot(rows));
    if (cfg.various) {
      setVarious(cfg.various);
      setSavedVarious(cfg.various);
    }
    if (cfg.discord) {
      setDiscord(cfg.discord);
      setSavedDiscord(cfg.discord);
    }
    if (cfg.condition_catalog) setCatalog(cfg.condition_catalog);
    setStrategyKey((current) =>
      cfg.strategies.some((s) => s.key === current) ? current : cfg.strategies[0]?.key || current,
    );
  }, []);

  useEffect(() => {
    void load().catch((err: Error) => setStatus(err.message));
  }, [load]);

  useEffect(() => {
    const onHash = () => setPage(pageFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    if (!status) return;
    const timer = window.setTimeout(() => setStatus(""), 6000);
    return () => window.clearTimeout(timer);
  }, [status]);

  function go(spec: string) {
    const [next, key] = spec.split(":") as [Page, string | undefined];
    if (!(next in PAGES)) return;
    if (next === "results") setResultStrategy(key || null);
    if (next === "strategies" && key) setStrategyKey(key);
    setPage(next);
    window.history.replaceState(null, "", `#${next}`);
    window.scrollTo(0, 0);
  }

  async function login(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setStatus("");
    try {
      await api("/api/admin/login", { method: "POST", body: JSON.stringify({ password }) });
      setPassword("");
      await load();
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "login failed");
    } finally {
      setBusy(false);
    }
  }

  async function logout() {
    await api("/api/admin/logout", { method: "POST" }).catch(() => undefined);
    setAuthed(false);
  }

  function patch(slot: number, fields: Partial<StrategyConfig>) {
    setItems((rows) => rows.map((row) => (row.slot === slot ? { ...row, ...fields } : row)));
  }

  function patchWeight(strategy: string, key: string, value: number) {
    setItems((rows) =>
      rows.map((row) =>
        row.key === strategy
          ? {
              ...row,
              weights: row.weights.map((item) => (item.key === key ? { ...item, current: value } : item)),
            }
          : row,
      ),
    );
  }

  // Thresholds and confirmation rules are two endpoints but one save here.
  async function saveStrategies() {
    setBusy(true);
    setStatus("");
    try {
      await api("/api/admin/thresholds", {
        method: "PUT",
        body: JSON.stringify({
          items: items.map((row) => ({
            slot: row.slot,
            threshold: row.threshold,
            cooldown_minutes: row.cooldown_minutes,
            cooldown_bypass_delta: row.cooldown_bypass_delta,
            max_fire_minute: row.max_fire_minute,
            max_fire_minute_1h: row.max_fire_minute_1h,
            enabled: row.enabled,
          })),
        }),
      });
      await api("/api/admin/rules", {
        method: "PUT",
        body: JSON.stringify({
          items: items.map((row) => ({
            slot: row.slot,
            success_window_minutes: row.success_window_minutes,
            expiration_buffer_minutes: row.expiration_buffer_minutes,
            infinite_ttl: row.infinite_ttl,
            team_specific: row.team_specific,
            expire_at_half_end: row.expire_at_half_end,
            enabled: row.enabled,
          })),
        }),
      });
      await load();
      setStatus("Saved. The scanner picks it up within ~15s.");
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "save failed");
    } finally {
      setBusy(false);
    }
  }

  function discardStrategies() {
    setItems((rows) => rows.map((row) => ({ ...row, ...(saved[row.slot] || {}) })));
  }

  async function saveVarious() {
    setBusy(true);
    setStatus("");
    try {
      const body = await api<{ ok: boolean; various: SweetSpotConfig }>("/api/admin/various", {
        method: "PUT",
        body: JSON.stringify(various),
      });
      if (body.various) {
        setVarious(body.various);
        setSavedVarious(body.various);
      }
      setStatus("Board filters saved. The live board picks them up on the next refresh.");
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "save failed");
    } finally {
      setBusy(false);
    }
  }

  async function saveDiscord() {
    setBusy(true);
    setStatus("");
    try {
      const body = await api<{ ok: boolean; discord: DiscordState }>("/api/admin/discord", {
        method: "PUT",
        body: JSON.stringify(discord),
      });
      if (body.discord) {
        setDiscord(body.discord);
        setSavedDiscord(body.discord);
      }
      setStatus("Discord settings saved. The bot picks them up within a few seconds.");
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "save failed");
    } finally {
      setBusy(false);
    }
  }

  async function saveWeight(strategy: string, key: string, value: number) {
    const body = await api<{ weights: WeightRow[] }>("/api/admin/weights", {
      method: "PUT",
      body: JSON.stringify({ strategy, key, value }),
    });
    setItems((rows) => rows.map((row) => (row.key === strategy ? { ...row, weights: body.weights } : row)));
  }

  async function applyPreset(strategy: string, preset: string) {
    const body = await api<{ weights: WeightRow[]; conditions?: ExtraCondition[] }>("/api/admin/weights/preset", {
      method: "POST",
      body: JSON.stringify({ strategy, preset }),
    });
    setItems((rows) =>
      rows.map((row) =>
        row.key === strategy
          ? {
              ...row,
              weights: body.weights,
              conditions: body.conditions != null ? body.conditions : row.conditions,
            }
          : row,
      ),
    );
    setStatus(`Applied ${preset}.`);
  }

  async function savePresetAs() {
    if (!current) return;
    const name = presetName.trim();
    if (!name) {
      setStatus("Name the preset first.");
      return;
    }
    setBusy(true);
    setStatus("");
    try {
      const body = await api<{
        weights: WeightRow[];
        saved_presets: string[];
        name: string;
        conditions?: ExtraCondition[];
      }>("/api/admin/weights/preset/save", {
        method: "POST",
        body: JSON.stringify({
          strategy: current.key,
          name,
          weights: Object.fromEntries(current.weights.map((row) => [row.key, row.current])),
          conditions: current.conditions || [],
        }),
      });
      setItems((rows) =>
        rows.map((row) =>
          row.key === current.key
            ? {
                ...row,
                weights: body.weights,
                saved_presets: body.saved_presets,
                conditions: body.conditions || row.conditions,
              }
            : row,
        ),
      );
      setPresetName("");
      setStatus(`Saved preset ${body.name}.`);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "save failed");
    } finally {
      setBusy(false);
    }
  }

  async function persistConditions(strategy: string, rows: ExtraCondition[]) {
    try {
      const body = await api<{ conditions: ExtraCondition[] }>("/api/admin/conditions", {
        method: "PUT",
        body: JSON.stringify({ strategy, conditions: rows }),
      });
      setItems((list) => list.map((row) => (row.key === strategy ? { ...row, conditions: body.conditions || rows } : row)));
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "conditions save failed");
    }
  }

  function setConditions(strategy: string, slot: number, rows: ExtraCondition[]) {
    patch(slot, { conditions: rows });
    window.clearTimeout(condTimer.current);
    condTimer.current = window.setTimeout(() => {
      void persistConditions(strategy, rows);
    }, 250);
  }

  async function resetWeights(strategy: string) {
    const body = await api<{ weights: WeightRow[] }>("/api/admin/weights/reset", {
      method: "POST",
      body: JSON.stringify({ strategy }),
    });
    setItems((rows) => rows.map((row) => (row.key === strategy ? { ...row, weights: body.weights } : row)));
    setStatus("Formula reset to defaults.");
  }

  const current = useMemo(() => items.find((row) => row.key === strategyKey) || items[0], [items, strategyKey]);
  const meta: StrategyMeta[] = useMemo(
    () => items.map((row) => ({ key: row.key, short: row.short, name: row.name, enabled: row.enabled })),
    [items],
  );
  const dirty = useMemo(() => {
    const out: { slot: number; field: SettingField }[] = [];
    for (const row of items) {
      const was = saved[row.slot];
      if (!was) continue;
      for (const field of SETTING_FIELDS) if (row[field] !== was[field]) out.push({ slot: row.slot, field });
    }
    return out;
  }, [items, saved]);

  useEffect(() => {
    if (!dirty.length) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty.length]);

  if (!configured) {
    return (
      <div className="adm-login">
        <h1>Admin is off</h1>
        <p>
          Set the <code>ADMIN_PASSWORD</code> variable on the API service, then reload.
        </p>
      </div>
    );
  }

  if (!authed) {
    return (
      <form className="adm-login" onSubmit={(event) => void login(event)}>
        <p className="adm-kicker">Kalchas</p>
        <h1>Admin</h1>
        <p>
          The <code>ADMIN_PASSWORD</code> environment variable.
        </p>
        <label>
          Password
          <input
            type="password"
            value={password}
            autoComplete="current-password"
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        <button type="submit" className="kit-btn is-primary" disabled={busy || !password}>
          Enter
        </button>
        {status ? <p className="kit-error">{status}</p> : null}
      </form>
    );
  }

  const insightsPage = page === "results" || page === "visitors";

  return (
    <div className="adm-shell">
      <aside className="adm-side">
        <div className="adm-brand">
          <b>Kalchas</b>
          <span>Admin</span>
        </div>
        <NavItem page="overview" on={page === "overview"} onClick={() => go("overview")} />
        <div className="adm-nav-group">Insights</div>
        <NavItem page="results" on={page === "results"} onClick={() => go("results")} />
        <NavItem page="visitors" on={page === "visitors"} onClick={() => go("visitors")} />
        <div className="adm-nav-group">Strategy</div>
        <NavItem
          page="strategies"
          on={page === "strategies"}
          onClick={() => go("strategies")}
          badge={dirty.length ? <span className="adm-dot-warn" title="Unsaved changes" /> : null}
        />
        <NavItem page="board" on={page === "board"} onClick={() => go("board")} />
        <div className="adm-nav-group">Distribution</div>
        <NavItem page="recap" on={page === "recap"} onClick={() => go("recap")} />
        <NavItem page="tips" on={page === "tips"} onClick={() => go("tips")} />
        <NavItem page="discord" on={page === "discord"} onClick={() => go("discord")} />
        <div className="adm-side-foot">
          <a href="/" className="adm-nav-item">
            ← Live board
          </a>
          <button type="button" className="adm-nav-item" onClick={() => void logout()}>
            Log out
          </button>
        </div>
      </aside>

      <div className="adm-main">
        <div className="adm-topbar">
          <div>
            <div className="adm-crumb">{PAGES[page].group}</div>
            <h1>{PAGES[page].title}</h1>
          </div>
          <div className="adm-spacer" />
          {insightsPage ? (
            <RangePicker
              range={range}
              onChange={setRange}
              minDate={page === "visitors" ? isoDay(29) : undefined}
            />
          ) : null}
        </div>

        <main className="adm-page">
          {page === "overview" ? (
            <AdminOverview api={api} zone={zone} strategies={meta} discord={savedDiscord} onGo={go} />
          ) : null}
          {page === "results" ? (
            <AdminResults
              api={api}
              range={range}
              zone={zone}
              strategies={meta}
              strategy={resultStrategy}
              onStrategy={setResultStrategy}
            />
          ) : null}
          {page === "visitors" ? <AdminVisitors api={api} range={range} zone={zone} /> : null}
          {page === "strategies" && current ? (
            <StrategiesPage
              items={items}
              current={current}
              zone={zone}
              catalog={catalog}
              presetName={presetName}
              busy={busy}
              dirty={dirty}
              onPick={setStrategyKey}
              onPatch={patch}
              onPatchWeight={patchWeight}
              onSaveWeight={(strategy, key, value) => void saveWeight(strategy, key, value)}
              onApplyPreset={(strategy, preset) => void applyPreset(strategy, preset)}
              onPresetName={setPresetName}
              onSavePreset={() => void savePresetAs()}
              onResetWeights={(strategy) => void resetWeights(strategy)}
              onConditions={setConditions}
              onSave={() => void saveStrategies()}
              onDiscard={discardStrategies}
              onGo={go}
            />
          ) : null}
          {page === "board" ? (
            <SweetSpotCard
              value={various}
              saved={savedVarious}
              busy={busy}
              onChange={setVarious}
              onSave={() => void saveVarious()}
              onDiscard={() => setVarious(savedVarious)}
            />
          ) : null}
          {page === "recap" ? <AdminRecap api={api} /> : null}
          {page === "tips" ? <AdminTips api={api} /> : null}
          {page === "discord" ? (
            <DiscordPage
              value={discord}
              saved={savedDiscord}
              busy={busy}
              onChange={setDiscord}
              onSave={() => void saveDiscord()}
              onDiscard={() => setDiscord(savedDiscord)}
            />
          ) : null}
        </main>
      </div>
      {status ? (
        <div className="adm-toast" role="status">
          {status}
        </div>
      ) : null}
    </div>
  );
}

/* ---------------------------------------------------------------- strategies */

function numberOrNull(raw: string): number | null {
  return raw === "" ? null : Number(raw);
}

function Field({
  label,
  help,
  changed,
  children,
}: {
  label: string;
  help?: string;
  changed?: boolean;
  children: ReactNode;
}) {
  return (
    <label className={`adm-field ${changed ? "is-dirty" : ""}`}>
      {label}
      {children}
      {help ? <span className="adm-help">{help}</span> : null}
    </label>
  );
}

function SaveBar({
  count,
  busy,
  note,
  onSave,
  onDiscard,
}: {
  count: number;
  busy: boolean;
  note: string;
  onSave: () => void;
  onDiscard: () => void;
}) {
  if (!count) return null;
  return (
    <div className="adm-savebar">
      <span>
        <b>{count}</b> unsaved change{count === 1 ? "" : "s"}. {note}
      </span>
      <span className="adm-spacer" />
      <button type="button" className="kit-btn" disabled={busy} onClick={onDiscard}>
        Discard
      </button>
      <button type="button" className="kit-btn is-primary" disabled={busy} onClick={onSave}>
        {busy ? "Saving…" : "Save changes"}
      </button>
    </div>
  );
}

function StrategiesPage({
  items,
  current,
  zone,
  catalog,
  presetName,
  busy,
  dirty,
  onPick,
  onPatch,
  onPatchWeight,
  onSaveWeight,
  onApplyPreset,
  onPresetName,
  onSavePreset,
  onResetWeights,
  onConditions,
  onSave,
  onDiscard,
  onGo,
}: {
  items: StrategyConfig[];
  current: StrategyConfig;
  zone: string;
  catalog: ConditionCatalog;
  presetName: string;
  busy: boolean;
  dirty: { slot: number; field: SettingField }[];
  onPick: (key: string) => void;
  onPatch: (slot: number, fields: Partial<StrategyConfig>) => void;
  onPatchWeight: (strategy: string, key: string, value: number) => void;
  onSaveWeight: (strategy: string, key: string, value: number) => void;
  onApplyPreset: (strategy: string, preset: string) => void;
  onPresetName: (name: string) => void;
  onSavePreset: () => void;
  onResetWeights: (strategy: string) => void;
  onConditions: (strategy: string, slot: number, rows: ExtraCondition[]) => void;
  onSave: () => void;
  onDiscard: () => void;
  onGo: (spec: string) => void;
}) {
  const [period, setPeriod] = useState<Range>(() => defaultRange("30"));
  const [stats, setStats] = useState<ResultsInsights | null>(null);

  useEffect(() => {
    if (!rangeValid(period)) return;
    let live = true;
    void api<ResultsInsights>(`/api/admin/insights/results?${rangeQuery(period, zone).toString()}`)
      .then((body) => {
        if (live) setStats(body);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [period, zone]);

  const byKey = Object.fromEntries((stats?.by_strategy || []).map((row) => [row.strategy, row.current]));
  const mine = byKey[current.key];
  const changed = (field: SettingField) => dirty.some((d) => d.slot === current.slot && d.field === field);
  const c = current;

  return (
    <div className="adm-split">
      <article className="kit-card adm-st-list">
        <div className="adm-st-period">
          <div className="adm-label">Hit rate over</div>
          <RangePicker range={period} onChange={setPeriod} compact />
          <div className="adm-help">{rangeValid(period) ? fmtWindow(stats?.window) : "Pick a From date on or before the To date"}</div>
        </div>
        <div className="adm-st-items">
          {items.map((row) => {
            const s = byKey[row.key];
            const rowDirty = dirty.some((d) => d.slot === row.slot);
            return (
              <button
                key={row.key}
                type="button"
                className={`adm-st-item ${row.key === current.key ? "is-on" : ""}`}
                title={row.name}
                onClick={() => onPick(row.key)}
              >
                <span className={`adm-onoff ${row.enabled ? "" : "is-off"}`} />
                <span className="kit-tag">{row.short}</span>
                {rowDirty ? <span className="adm-dot-warn" title="Unsaved changes" /> : <span />}
                <span className="adm-st-rate kit-num">
                  <b>{pct(s?.hit_rate)}</b>n {s?.settled ?? 0}
                </span>
              </button>
            );
          })}
        </div>
      </article>

      <div className="adm-st-main">
        <article className="kit-card">
          <header className="adm-st-head">
            <span className="kit-tag is-big">{c.short}</span>
            <div className="adm-st-title">
              <b>{c.name}</b>
              <span>
                {mine
                  ? `${fmtWindow(stats?.window)}: ${mine.total} fired · ${pct(mine.hit_rate)} hit on ${mine.settled} settled`
                  : "Loading results…"}
              </span>
            </div>
            <div className="adm-st-actions">
              <label className={`kit-toggle ${changed("enabled") ? "is-dirty" : ""}`}>
                <input type="checkbox" checked={c.enabled} onChange={(e) => onPatch(c.slot, { enabled: e.target.checked })} />
                Enabled
              </label>
              <button type="button" className="kit-link" onClick={() => onGo(`results:${c.key}`)}>
                See results →
              </button>
            </div>
          </header>
          {c.blurb ? <p className="adm-blurb">{c.blurb}</p> : null}

          <section className="adm-sec">
            <h3>When it fires</h3>
            <p>The fire threshold, how long to wait before firing again, and the latest minute it may fire.</p>
            <div className="adm-fields">
              <Field label="Fire threshold" help="Fires when the value reaches this" changed={changed("threshold")}>
                <input type="number" step="0.1" value={c.threshold} onChange={(e) => onPatch(c.slot, { threshold: Number(e.target.value) })} />
              </Field>
              <Field label="Cooldown (min)" help="Wait before firing again on the same match" changed={changed("cooldown_minutes")}>
                <input type="number" min={0} step={1} value={c.cooldown_minutes} onChange={(e) => onPatch(c.slot, { cooldown_minutes: Number(e.target.value) })} />
              </Field>
              <Field label="Bypass if value rises by" help="Re-fire inside the cooldown on a jump this big" changed={changed("cooldown_bypass_delta")}>
                <input
                  type="number"
                  step="0.1"
                  value={c.cooldown_bypass_delta ?? 0}
                  onChange={(e) => onPatch(c.slot, { cooldown_bypass_delta: Number(e.target.value) })}
                />
              </Field>
              <Field label="Don't fire after minute" help="Blank = any minute. 90+4 counts as 94." changed={changed("max_fire_minute")}>
                <input
                  type="number"
                  min={1}
                  max={130}
                  step={1}
                  placeholder="Off"
                  value={c.max_fire_minute ?? ""}
                  onChange={(e) => onPatch(c.slot, { max_fire_minute: numberOrNull(e.target.value) })}
                />
              </Field>
              <Field label="1st half: don't fire after" help="Only the 1st half and HT, incl. its stoppage" changed={changed("max_fire_minute_1h")}>
                <input
                  type="number"
                  min={1}
                  max={60}
                  step={1}
                  placeholder="Off"
                  value={c.max_fire_minute_1h ?? ""}
                  onChange={(e) => onPatch(c.slot, { max_fire_minute_1h: numberOrNull(e.target.value) })}
                />
              </Field>
            </div>
          </section>

          <section className="adm-sec">
            <h3>How it settles</h3>
            <p>How an alert moves from Open to Hit or Miss.</p>
            <div className="adm-fields">
              <Field label="Success window (min)" help="A goal inside this counts as a hit" changed={changed("success_window_minutes")}>
                <input
                  type="number"
                  min={0}
                  value={c.success_window_minutes}
                  onChange={(e) => onPatch(c.slot, { success_window_minutes: Number(e.target.value) })}
                />
              </Field>
              <Field label="Expire buffer (min)" changed={changed("expiration_buffer_minutes")}>
                <input
                  type="number"
                  min={0}
                  value={c.expiration_buffer_minutes}
                  onChange={(e) => onPatch(c.slot, { expiration_buffer_minutes: Number(e.target.value) })}
                />
              </Field>
            </div>
            <div className="adm-toggles">
              <label className={`kit-toggle ${changed("infinite_ttl") ? "is-dirty" : ""}`}>
                <input type="checkbox" checked={c.infinite_ttl} onChange={(e) => onPatch(c.slot, { infinite_ttl: e.target.checked })} />
                Wait until match end (no window)
              </label>
              <label className={`kit-toggle ${changed("team_specific") ? "is-dirty" : ""}`}>
                <input type="checkbox" checked={c.team_specific} onChange={(e) => onPatch(c.slot, { team_specific: e.target.checked })} />
                Only the trigger team’s goal counts
              </label>
              <label className={`kit-toggle ${changed("expire_at_half_end") ? "is-dirty" : ""}`}>
                <input
                  type="checkbox"
                  checked={Boolean(c.expire_at_half_end)}
                  onChange={(e) => onPatch(c.slot, { expire_at_half_end: e.target.checked })}
                />
                Expire at the end of the current half
              </label>
            </div>
          </section>

          <section className="adm-sec">
            <h3>Formula</h3>
            <p>Weights and extra conditions. These save as soon as you let go of a slider, separately from the save bar.</p>
            <div className="admin-weights-layout">
              <div>
                <div className="adm-preset-row">
                  <select
                    value=""
                    onChange={(e) => {
                      if (e.target.value) onApplyPreset(c.key, e.target.value);
                    }}
                  >
                    <option value="">Apply preset…</option>
                    <optgroup label="Built in">
                      {c.presets.map((preset) => (
                        <option key={preset} value={preset}>
                          {preset}
                        </option>
                      ))}
                    </optgroup>
                    {(c.saved_presets || []).length > 0 ? (
                      <optgroup label="Saved">
                        {c.saved_presets.map((preset) => (
                          <option key={preset} value={preset}>
                            {preset}
                          </option>
                        ))}
                      </optgroup>
                    ) : null}
                  </select>
                  <input type="text" value={presetName} placeholder="Preset name" maxLength={40} onChange={(e) => onPresetName(e.target.value)} />
                  <button type="button" className="kit-btn" disabled={busy} onClick={onSavePreset}>
                    Save preset as
                  </button>
                  <button type="button" className="kit-btn" onClick={() => onResetWeights(c.key)}>
                    Reset
                  </button>
                </div>
                <pre className="admin-eq">{c.equation}</pre>
                {c.weights.map((weight) => {
                  const suggested = weight.suggested || String(weight.default);
                  return (
                    <label key={weight.key} className="admin-slider">
                      <span>
                        {weight.label}
                        <small>{weight.current}</small>
                      </span>
                      <div className="admin-slider-controls">
                        <input
                          type="range"
                          min={weight.min}
                          max={weight.max}
                          step={weight.step}
                          value={weight.current}
                          onChange={(e) => onPatchWeight(c.key, weight.key, Number(e.target.value))}
                          onMouseUp={(e) => onSaveWeight(c.key, weight.key, Number(e.currentTarget.value))}
                          onTouchEnd={(e) => onSaveWeight(c.key, weight.key, Number(e.currentTarget.value))}
                        />
                        <input
                          type="number"
                          min={weight.min}
                          max={weight.max}
                          step={weight.step}
                          value={weight.current}
                          onChange={(e) => onPatchWeight(c.key, weight.key, Number(e.target.value))}
                          onBlur={(e) => onSaveWeight(c.key, weight.key, Number(e.currentTarget.value))}
                        />
                      </div>
                      <small>
                        {weight.description}
                        {suggested ? (
                          <>
                            {" "}
                            <span className="admin-suggested">Suggested: {suggested}</span>
                          </>
                        ) : null}
                        {weight.current !== weight.default ? ` · default ${weight.default}` : ""}
                      </small>
                    </label>
                  );
                })}
              </div>
              <div className="admin-weights-aside">
                <AdminPreview
                  strategy={c.key}
                  short={c.short}
                  weights={Object.fromEntries(c.weights.map((row) => [row.key, row.current]))}
                  conditions={c.conditions || []}
                  api={api}
                />
                <AdminConditions catalog={catalog} rows={c.conditions || []} onChange={(rows) => onConditions(c.key, c.slot, rows)} />
              </div>
            </div>
          </section>
        </article>
        <SaveBar
          count={dirty.length}
          busy={busy}
          note="The scanner picks them up within ~15s of saving."
          onSave={onSave}
          onDiscard={onDiscard}
        />
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- board filters */

function halfCheck(start: number, end: number, lo: number, hi: number): boolean {
  return Number.isFinite(start) && Number.isFinite(end) && start >= lo && end <= hi && start < end;
}

function SweetSpotCard({
  value,
  saved,
  busy,
  onChange,
  onSave,
  onDiscard,
}: {
  value: SweetSpotConfig;
  saved: SweetSpotConfig;
  busy: boolean;
  onChange: (next: SweetSpotConfig) => void;
  onSave: () => void;
  onDiscard: () => void;
}) {
  const first = halfCheck(value.ht1_start, value.ht1_end, 0, 45);
  const second = halfCheck(value.ht2_start, value.ht2_end, 45, 90);
  const changes = (Object.keys(value) as (keyof SweetSpotConfig)[]).filter((k) => value[k] !== saved[k]).length;
  const set = (field: keyof SweetSpotConfig, raw: string) => onChange({ ...value, [field]: Number(raw) });

  const segment = (start: number, end: number, lo: number, ok: boolean) => {
    const toEnd = ok && end === lo + 45;
    const extra = toEnd && value.include_injury_time;
    const left = ((Math.min(Math.max(start, lo), lo + 45) - lo) / 45) * 100;
    const right = ((Math.min(Math.max(end, lo), lo + 45) - lo) / 45) * 100;
    return (
      <div className="ss-seg">
        <div className="ss-track">
          {ok ? <span className={`ss-win ${extra ? "is-to-end" : ""}`} style={{ left: `${left}%`, width: `${right - left}%` }} /> : null}
          {[0, 15, 30, 45].map((t) => (
            <span key={t} className={`ss-tick ${t === 0 ? "is-first" : ""}`} style={{ left: `${(t / 45) * 100}%` }}>
              {lo + t}′
            </span>
          ))}
        </div>
        <span className={`ss-x ${extra ? "is-on" : ""}`} title={extra ? `${lo + 45}′+x counts` : "Injury time not counted"} />
      </div>
    );
  };

  const half = (title: string, span: string, sf: keyof SweetSpotConfig, ef: keyof SweetSpotConfig, ok: boolean, lo: number, hi: number) => {
    const start = value[sf] as number;
    const end = value[ef] as number;
    return (
      <div className={`ss-half ${ok ? "" : "is-bad"}`}>
        <div className="ss-half-head">
          <b>{title}</b>
          <span>{span}</span>
        </div>
        <div className="ss-range">
          <label>
            From
            <span className="ss-in">
              <input type="number" min={lo} max={hi} value={start} onChange={(e) => set(sf, e.target.value)} />
              <i>′</i>
            </span>
          </label>
          <span className="ss-dash">–</span>
          <label>
            To
            <span className="ss-in">
              <input type="number" min={lo} max={hi} value={end} onChange={(e) => set(ef, e.target.value)} />
              <i>′</i>
            </span>
          </label>
        </div>
        <div className="ss-sum">
          {ok ? (
            <>
              Shows matches from <b>{start}′</b> to{" "}
              <b>
                {end}′{value.include_injury_time && end === hi ? "+x" : ""}
              </b>{" "}
              · {end - start} min window
            </>
          ) : (
            `Pick a start before the end, inside ${lo}′–${hi}′`
          )}
        </div>
      </div>
    );
  };

  return (
    <>
      <article className="kit-card">
        <section className="adm-sec">
          <h3>Sweet spot t</h3>
          <p>When Sweet spot t is on, the live board only shows matches whose clock is inside one of these two windows.</p>
          <div className="ss-line" aria-hidden="true">
            {segment(value.ht1_start, value.ht1_end, 0, first)}
            <div className="ss-ht">HT</div>
            {segment(value.ht2_start, value.ht2_end, 45, second)}
          </div>
          <div className="ss-halves">
            {half("1st half", "0′ – 45′", "ht1_start", "ht1_end", first, 0, 45)}
            {half("2nd half", "45′ – 90′", "ht2_start", "ht2_end", second, 45, 90)}
          </div>
          <label className="kit-toggle ss-inj">
            <input
              type="checkbox"
              checked={value.include_injury_time}
              onChange={(e) => onChange({ ...value, include_injury_time: e.target.checked })}
            />
            Include injury time
            <span>(the striped end of each half: 45′+x and 90′+x count when a window ends at 45′ or 90′)</span>
          </label>
        </section>
      </article>
      {changes && !(first && second) ? <p className="kit-error">Fix the highlighted half before saving.</p> : null}
      <SaveBar
        count={first && second ? changes : 0}
        busy={busy}
        note="The live board picks them up on its next refresh."
        onSave={onSave}
        onDiscard={onDiscard}
      />
    </>
  );
}

/* ---------------------------------------------------------------- discord */

function DiscordPage({
  value,
  saved,
  busy,
  onChange,
  onSave,
  onDiscard,
}: {
  value: DiscordState;
  saved: DiscordState;
  busy: boolean;
  onChange: (next: DiscordState) => void;
  onSave: () => void;
  onDiscard: () => void;
}) {
  const changes = (Object.keys(value) as (keyof DiscordState)[]).filter((k) => (value[k] ?? null) !== (saved[k] ?? null)).length;
  const channel = (title: string, idField: "paid_channel_id" | "free_channel_id", onField: "paid_enabled" | "free_enabled") => (
    <article className="kit-card">
      <section className="adm-sec">
        <h3>{title}</h3>
        <div className="adm-fields">
          <Field label="Channel id" changed={value[idField] !== saved[idField]}>
            <input
              type="text"
              placeholder="e.g. 1234567890123456"
              value={value[idField] ?? ""}
              onChange={(e) => onChange({ ...value, [idField]: e.target.value || null })}
            />
          </Field>
        </div>
        <div className="adm-toggles">
          <label className={`kit-toggle ${value[onField] !== saved[onField] ? "is-dirty" : ""}`}>
            <input type="checkbox" checked={value[onField]} onChange={(e) => onChange({ ...value, [onField]: e.target.checked })} />
            Cross-post to this channel
          </label>
          <span className={`adm-chip ${value[idField] && value[onField] ? "is-ok" : "is-warn"}`}>
            {!value[idField] ? "No channel id" : value[onField] ? "Posting" : "Switched off"}
          </span>
        </div>
      </section>
    </article>
  );
  return (
    <>
      <p className="adm-intro">
        Channel ids the bot cross-posts fires and outcomes to, with a per-channel kill switch. The bot token stays a
        Railway secret, not a setting here.
      </p>
      <div className="kit-grid-2 kit-grid-even">
        {channel("Paid channel", "paid_channel_id", "paid_enabled")}
        {channel("Free channel", "free_channel_id", "free_enabled")}
      </div>
      <SaveBar count={changes} busy={busy} note="The bot picks them up within a few seconds." onSave={onSave} onDiscard={onDiscard} />
    </>
  );
}
