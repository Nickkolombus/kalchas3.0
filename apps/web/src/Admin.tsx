import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { AdminConditions, type ConditionCatalog, type ExtraCondition } from "./AdminConditions";
import { AdminPreview } from "./AdminPreview";
import { AdminResults } from "./AdminResults";
import { AdminTips } from "./AdminTips";

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

type Tab = "thresholds" | "rules" | "weights" | "results" | "tips" | "various";

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

function slopeToDegrees(slope: number, kScale: number): number {
  return (Math.atan(slope / Math.max(kScale, 1e-9)) * 180) / Math.PI;
}

function omegaDegreeHint(weights: WeightRow[], key: string): string | null {
  if (key !== "min_accel" && key !== "min_baseline_slope") return null;
  const kScale = weights.find((row) => row.key === "k_scale")?.current ?? 1.5;
  const slope = weights.find((row) => row.key === key)?.current ?? 0;
  return `≈ ${slopeToDegrees(slope, kScale).toFixed(0)}° at k_scale ${kScale}`;
}

export function AdminApp() {
  const [configured, setConfigured] = useState(true);
  const [authed, setAuthed] = useState(false);
  const [password, setPassword] = useState("");
  const [status, setStatus] = useState("");
  const [tab, setTab] = useState<Tab>("thresholds");
  const [items, setItems] = useState<StrategyConfig[]>([]);
  const [strategyKey, setStrategyKey] = useState("rule_of_three");
  const [resultStrategies, setResultStrategies] = useState<string[]>([]);
  const [presetName, setPresetName] = useState("");
  const [busy, setBusy] = useState(false);
  const [various, setVarious] = useState<SweetSpotConfig>(DEFAULT_SWEET_SPOT);
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
      condition_catalog?: ConditionCatalog;
    }>("/api/admin/config");
    setItems(
      cfg.strategies.map((row) => ({
        ...row,
        conditions: row.conditions || [],
      })),
    );
    if (cfg.various) setVarious(cfg.various);
    if (cfg.condition_catalog) setCatalog(cfg.condition_catalog);
    setStrategyKey((current) =>
      cfg.strategies.some((s) => s.key === current) ? current : cfg.strategies[0]?.key || current,
    );
  }, []);

  useEffect(() => {
    void load().catch((err: Error) => setStatus(err.message));
  }, [load]);

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

  function patch(slot: number, fields: Partial<StrategyConfig>) {
    setItems((rows) => rows.map((row) => (row.slot === slot ? { ...row, ...fields } : row)));
  }

  function patchWeight(strategy: string, key: string, value: number) {
    setItems((rows) =>
      rows.map((row) =>
        row.key === strategy
          ? {
              ...row,
              weights: row.weights.map((item) =>
                item.key === key ? { ...item, current: value } : item,
              ),
            }
          : row,
      ),
    );
  }

  async function saveThresholds() {
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
            enabled: row.enabled,
          })),
        }),
      });
      await load();
      setStatus("Thresholds saved. Scanner picks them up within ~15s.");
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "save failed");
    } finally {
      setBusy(false);
    }
  }

  async function saveVarious() {
    setBusy(true);
    setStatus("");
    try {
      const saved = await api<{ ok: boolean; various: SweetSpotConfig }>("/api/admin/various", {
        method: "PUT",
        body: JSON.stringify(various),
      });
      if (saved.various) setVarious(saved.various);
      setStatus("Various settings saved. The live board picks them up on the next refresh.");
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "save failed");
    } finally {
      setBusy(false);
    }
  }

  async function saveRules() {
    setBusy(true);
    setStatus("");
    try {
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
      setStatus("Confirmation rules saved.");
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
    setItems((rows) =>
      rows.map((row) => (row.key === strategy ? { ...row, weights: body.weights } : row)),
    );
  }

  async function applyPreset(strategy: string, preset: string) {
      const body = await api<{ weights: WeightRow[]; conditions?: ExtraCondition[] }>(
        "/api/admin/weights/preset",
        {
          method: "POST",
          body: JSON.stringify({ strategy, preset }),
        },
      );
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
      setItems((current) =>
        current.map((row) =>
          row.key === strategy ? { ...row, conditions: body.conditions || rows } : row,
        ),
      );
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
    setItems((rows) =>
      rows.map((row) => (row.key === strategy ? { ...row, weights: body.weights } : row)),
    );
    setStatus("Reset to defaults.");
  }

  const current = useMemo(
    () => items.find((row) => row.key === strategyKey) || items[0],
    [items, strategyKey],
  );

  if (!configured) {
    return (
      <div className="admin-login">
        <h1>Admin is off</h1>
        <p>Set the <code>ADMIN_PASSWORD</code> variable on the API service, then reload.</p>
      </div>
    );
  }

  if (!authed) {
    return (
      <form className="admin-login" onSubmit={(event) => void login(event)}>
        <p className="admin-kicker">Kalchas</p>
        <h1>Admin</h1>
        <p>Same password as 2.2 - the <code>ADMIN_PASSWORD</code> environment variable.</p>
        <label>
          Password
          <input
            type="password"
            value={password}
            autoComplete="current-password"
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        <button type="submit" disabled={busy || !password}>
          Enter
        </button>
        {status ? <p className="admin-status">{status}</p> : null}
      </form>
    );
  }

  return (
    <div className="admin-shell">
      <aside className="admin-side">
        <div className="admin-side-title">Admin</div>
        <a href="/" className="admin-back">
          ← Live board
        </a>
        <button
          type="button"
          className={tab === "thresholds" ? "is-on" : ""}
          onClick={() => setTab("thresholds")}
        >
          Thresholds
        </button>
        <button
          type="button"
          className={tab === "rules" ? "is-on" : ""}
          onClick={() => setTab("rules")}
        >
          Confirmation
        </button>
        <button
          type="button"
          className={tab === "weights" ? "is-on" : ""}
          onClick={() => setTab("weights")}
        >
          Formula weights
        </button>
        <button
          type="button"
          className={tab === "results" ? "is-on" : ""}
          onClick={() => setTab("results")}
        >
          Results
        </button>
        <button
          type="button"
          className={tab === "tips" ? "is-on" : ""}
          onClick={() => setTab("tips")}
        >
          Tips feed
        </button>
        <button
          type="button"
          className={tab === "various" ? "is-on" : ""}
          onClick={() => setTab("various")}
        >
          Various
        </button>
      </aside>
      <main className="admin-main">
        {tab === "thresholds" ? (
          <header>
            <h1>Basic thresholds</h1>
            <p>
              When a strategy fires, how long to wait, and whether it is on. Omega
              gates live under Formula weights - its Fire slider is unused.
            </p>
          </header>
        ) : null}
        {tab === "rules" ? (
          <header>
            <h1>Confirmation rules</h1>
            <p>How Recent signals move from Monitoring to Confirmed or Expired.</p>
          </header>
        ) : null}
        {tab === "weights" && current ? (
          <header>
            <h1>Formula weights</h1>
            <p>
              {current.short} · {current.name}. {current.blurb}
            </p>
          </header>
        ) : null}
        {tab === "various" ? (
          <header>
            <h1>Various</h1>
            <p>
              Board-wide filters that are not tied to one strategy. Sweet spot t
              uses these windows.
            </p>
          </header>
        ) : null}
        {tab === "results" ? (
          <AdminResults
            strategies={items.map((row) => ({
              key: row.key,
              short: row.short,
              name: row.name,
            }))}
            selected={resultStrategies}
            onToggle={(key) =>
              setResultStrategies((current) =>
                current.includes(key)
                  ? current.filter((item) => item !== key)
                  : [...current, key],
              )
            }
            api={api}
          />
        ) : null}
        {tab === "tips" ? <AdminTips api={api} /> : null}
        {tab === "various" ? (
          <>
            <article className="admin-tab-panel">
              <h2>Sweet spot t</h2>
              <p className="admin-hint">
                When Sweet spot t is checked on the live board, only matches inside
                these clocks stay visible. Injury time is 45'+x' and 90'+x' for
                both halves when the feed has the extra minute. The referee's
                announced total is not in this API.
              </p>
              <div className="admin-fields">
                <div className="admin-range">
                  <span>1st HT</span>
                  <label>
                    From
                    <input
                      type="number"
                      min={0}
                      max={130}
                      value={various.ht1_start}
                      onChange={(event) =>
                        setVarious((current) => ({
                          ...current,
                          ht1_start: Number(event.target.value),
                        }))
                      }
                    />
                  </label>
                  <span className="admin-range-sep">-</span>
                  <label>
                    To
                    <input
                      type="number"
                      min={0}
                      max={130}
                      value={various.ht1_end}
                      onChange={(event) =>
                        setVarious((current) => ({
                          ...current,
                          ht1_end: Number(event.target.value),
                        }))
                      }
                    />
                  </label>
                </div>
                <div className="admin-range">
                  <span>2nd HT</span>
                  <label>
                    From
                    <input
                      type="number"
                      min={0}
                      max={130}
                      value={various.ht2_start}
                      onChange={(event) =>
                        setVarious((current) => ({
                          ...current,
                          ht2_start: Number(event.target.value),
                        }))
                      }
                    />
                  </label>
                  <span className="admin-range-sep">-</span>
                  <label>
                    To
                    <input
                      type="number"
                      min={0}
                      max={130}
                      value={various.ht2_end}
                      onChange={(event) =>
                        setVarious((current) => ({
                          ...current,
                          ht2_end: Number(event.target.value),
                        }))
                      }
                    />
                  </label>
                </div>
              </div>
              <label className="admin-toggle">
                <input
                  type="checkbox"
                  checked={various.include_injury_time}
                  onChange={(event) =>
                    setVarious((current) => ({
                      ...current,
                      include_injury_time: event.target.checked,
                    }))
                  }
                />
                Include injury time
              </label>
            </article>
            <div className="admin-actions">
              <button type="button" disabled={busy} onClick={() => void saveVarious()}>
                Save various
              </button>
            </div>
          </>
        ) : null}
        {tab !== "results" && tab !== "various" ? (
        <>
        <nav className="admin-tabs" role="tablist" aria-label="Strategy">
          {items.map((row) => (
            <button
              key={row.key}
              type="button"
              role="tab"
              aria-selected={current?.key === row.key}
              className={current?.key === row.key ? "is-on" : ""}
              title={row.name}
              onClick={() => setStrategyKey(row.key)}
            >
              {row.short}
            </button>
          ))}
        </nav>
        {tab === "thresholds" && current ? (
          <>
            <article className="admin-tab-panel">
              <div className="admin-card-head">
                <h2>
                  {current.short} · {current.name}
                </h2>
                <label className="admin-toggle">
                  <input
                    type="checkbox"
                    checked={current.enabled}
                    onChange={(event) => patch(current.slot, { enabled: event.target.checked })}
                  />
                  Enabled
                </label>
              </div>
              <p className="admin-hint">{current.blurb}</p>
              <div className="admin-fields">
                {current.slot === 6 ? (
                  <p className="admin-unused">
                    Fire threshold is unused for Omega. The engine fires on{" "}
                    <code>min_accel</code>, <code>min_baseline_slope</code>,{" "}
                    <code>pi_level_min</code>, and <code>min_shots</code> under Formula
                    weights (default min_accel 0.866 ≈ 30° at k_scale 1.5). Same surge
                    will not re-fire until it cools off.
                  </p>
                ) : (
                  <label>
                    Fire threshold
                    <input
                      type="number"
                      step="0.1"
                      value={current.threshold}
                      onChange={(event) =>
                        patch(current.slot, { threshold: Number(event.target.value) })
                      }
                    />
                  </label>
                )}
                <label>
                  Cooldown (min)
                  <input
                    type="number"
                    min={0}
                    step={1}
                    value={current.cooldown_minutes}
                    onChange={(event) =>
                      patch(current.slot, { cooldown_minutes: Number(event.target.value) })
                    }
                  />
                </label>
                {current.slot === 6 ? (
                  <p className="admin-unused">
                    Omega no longer uses a value-delta bypass. A fire locks until
                    linear ω falls below half of the last alert.
                  </p>
                ) : (
                  <label>
                    Bypass if value rises by
                    <input
                      type="number"
                      step="0.1"
                      value={current.cooldown_bypass_delta ?? 0}
                      onChange={(event) =>
                        patch(current.slot, {
                          cooldown_bypass_delta: Number(event.target.value),
                        })
                      }
                    />
                  </label>
                )}
              </div>
            </article>
            <div className="admin-actions">
              <button type="button" disabled={busy} onClick={() => void saveThresholds()}>
                Save thresholds
              </button>
            </div>
          </>
        ) : null}

        {tab === "rules" && current ? (
          <>
            <article className="admin-tab-panel">
              <h2>
                {current.short} · {current.name}
              </h2>
              <div className="admin-fields">
                <label>
                  Success window (min)
                  <input
                    type="number"
                    min={0}
                    value={current.success_window_minutes}
                    onChange={(event) =>
                      patch(current.slot, {
                        success_window_minutes: Number(event.target.value),
                      })
                    }
                  />
                </label>
                <label>
                  Expire buffer (min)
                  <input
                    type="number"
                    min={0}
                    value={current.expiration_buffer_minutes}
                    onChange={(event) =>
                      patch(current.slot, {
                        expiration_buffer_minutes: Number(event.target.value),
                      })
                    }
                  />
                </label>
              </div>
              <div className="admin-toggle-row">
                <label className="admin-toggle">
                  <input
                    type="checkbox"
                    checked={current.infinite_ttl}
                    onChange={(event) =>
                      patch(current.slot, { infinite_ttl: event.target.checked })
                    }
                  />
                  Wait until match end (no window)
                </label>
                <label className="admin-toggle">
                  <input
                    type="checkbox"
                    checked={current.team_specific}
                    onChange={(event) =>
                      patch(current.slot, { team_specific: event.target.checked })
                    }
                  />
                  Only the trigger team’s goal counts
                </label>
                <label className="admin-toggle">
                  <input
                    type="checkbox"
                    checked={Boolean(current.expire_at_half_end)}
                    onChange={(event) =>
                      patch(current.slot, { expire_at_half_end: event.target.checked })
                    }
                  />
                  Expire at the end of the current half
                </label>
              </div>
              <p className="admin-hint">
                When that box is on, Monitoring closes at HT in the first half (or at
                full time in the second), or when the success window runs out -
                whichever comes first. A goal in the same half can still confirm.
              </p>
            </article>
            <div className="admin-actions">
              <button type="button" disabled={busy} onClick={() => void saveRules()}>
                Save confirmation rules
              </button>
            </div>
          </>
        ) : null}

        {tab === "weights" && current ? (
          <div className="admin-weights-layout">
            <div>
            <div className="admin-weight-nav">
              <select
                value=""
                onChange={(event) => {
                  const preset = event.target.value;
                  if (preset) void applyPreset(current.key, preset);
                }}
              >
                <option value="">Apply preset…</option>
                <optgroup label="Built in">
                  {current.presets.map((preset) => (
                    <option key={preset} value={preset}>
                      {preset}
                    </option>
                  ))}
                </optgroup>
                {(current.saved_presets || []).length > 0 ? (
                  <optgroup label="Saved">
                    {current.saved_presets.map((preset) => (
                      <option key={preset} value={preset}>
                        {preset}
                      </option>
                    ))}
                  </optgroup>
                ) : null}
              </select>
              <input
                type="text"
                value={presetName}
                placeholder="Preset name"
                maxLength={40}
                onChange={(event) => setPresetName(event.target.value)}
              />
              <button type="button" disabled={busy} onClick={() => void savePresetAs()}>
                Save preset as
              </button>
              <button type="button" onClick={() => void resetWeights(current.key)}>
                Reset {current.name}
              </button>
            </div>
            <p className="admin-hint">
              Save preset as stores this strategy&apos;s formula weights and extra conditions.
              Built-in presets only apply weights.
            </p>
            <pre className="admin-eq">{current.equation}</pre>
            {current.key === "omega" ? (
              <p className="admin-omega-lead">
                Omega section - these gates are what <code>TeamOmega.meets</code> uses.
                Presets: Default (~30°), Sensitive, Confirmed surges only, Quiet / picky.
              </p>
            ) : null}
            {current.weights.map((weight) => {
              const degreeHint =
                current.key === "omega" ? omegaDegreeHint(current.weights, weight.key) : null;
              const suggested = weight.suggested || String(weight.default);
              return (
                <label key={weight.key} className="admin-slider">
                  <span>
                    {weight.label}
                    <small>
                      {weight.current}
                      {degreeHint ? ` · ${degreeHint}` : ""}
                    </small>
                  </span>
                  <div className="admin-slider-controls">
                    <input
                      type="range"
                      min={weight.min}
                      max={weight.max}
                      step={weight.step}
                      value={weight.current}
                      onChange={(event) =>
                        patchWeight(current.key, weight.key, Number(event.target.value))
                      }
                      onMouseUp={(event) =>
                        void saveWeight(
                          current.key,
                          weight.key,
                          Number(event.currentTarget.value),
                        )
                      }
                      onTouchEnd={(event) =>
                        void saveWeight(
                          current.key,
                          weight.key,
                          Number(event.currentTarget.value),
                        )
                      }
                    />
                    <input
                      type="number"
                      min={weight.min}
                      max={weight.max}
                      step={weight.step}
                      value={weight.current}
                      onChange={(event) =>
                        patchWeight(current.key, weight.key, Number(event.target.value))
                      }
                      onBlur={(event) =>
                        void saveWeight(current.key, weight.key, Number(event.currentTarget.value))
                      }
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
              strategy={current.key}
              short={current.short}
              weights={Object.fromEntries(current.weights.map((row) => [row.key, row.current]))}
              conditions={current.conditions || []}
              api={api}
            />
            <AdminConditions
              catalog={catalog}
              rows={current.conditions || []}
              onChange={(rows) => setConditions(current.key, current.slot, rows)}
            />
            </div>
          </div>
        ) : null}
        </>
        ) : null}
        {status ? <p className="admin-status">{status}</p> : null}
      </main>
    </div>
  );
}
