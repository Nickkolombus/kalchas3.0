import { useCallback, useEffect, useMemo, useState } from "react";

type Api = <T>(path: string, init?: RequestInit) => Promise<T>;

type Slot = "today" | "tomorrow" | "nightly";
type Style = "safer" | "balanced" | "bolder";

type TeamRef = { name: string; badge?: string | null; position?: number | null };

type Leg = {
  match_id: string;
  kickoff: string;
  league: string;
  country: string;
  home: TeamRef;
  away: TeamRef;
  watch: string;
  market: string;
  label: string;
  price: number;
  hit: number;
  n: number;
  brief: string;
  score: number;
};

type Compose = {
  slot: Slot;
  style: Style;
  style_blurb: string;
  day: string;
  today: string;
  status: "ready" | "preparing" | "none";
  window_label: string | null;
  stake: number;
  min_legs: number;
  max_legs: number;
  presets: number[];
  available: number;
  wanted: number;
  legs: Leg[];
  order: Record<Style, string[]>;
  selected: Leg[];
  combined: number | null;
  returns: number | null;
  can_post: boolean;
  exclude: string[];
  explanation: string;
  claude_ready: boolean;
};

type PostLog = Record<string, { ok: boolean; error?: string; ref?: string }>;

const SLOTS: { key: Slot; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "tomorrow", label: "Tomorrow" },
  { key: "nightly", label: "Nightly" },
];

const STYLES: { key: Style; label: string; desc: string }[] = [
  {
    key: "safer",
    label: "Safer",
    desc: "Shortest prices first, and only legs that came in at least 7 times in 10 recently.",
  },
  {
    key: "balanced",
    label: "Balanced",
    desc: "The strongest patterns of the day, in the order the watchlist ranks them.",
  },
  {
    key: "bolder",
    label: "Bolder",
    desc: "Legs whose recent record beats the price by the most. Longer odds, less likely to all come in.",
  },
];

const CHANNELS: { key: string; label: string }[] = [
  { key: "x", label: "X / Twitter" },
  { key: "telegram_free", label: "Telegram free" },
  { key: "telegram_paid", label: "Telegram paid" },
  { key: "discord_free", label: "Discord free" },
  { key: "discord_paid", label: "Discord paid" },
];

const PRESETS = [3, 5, 8, 12, 18];

function kickHm(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "";
  return at.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false });
}

function dayLabel(iso: string): string {
  const at = new Date(`${iso}T12:00:00Z`);
  if (Number.isNaN(at.getTime())) return iso;
  return at.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
}

function oneIn(odds: number): string {
  if (odds < 2) return "better than even";
  const n = Math.round(odds);
  if (n >= 10_000) return `about 1 in ${Math.round(n / 1000).toLocaleString()},000`;
  if (n >= 1000) return `about 1 in ${(Math.round(n / 100) * 100).toLocaleString()}`;
  return `about 1 in ${n}`;
}

const STYLE_NATURE: Record<Style, string> = {
  safer: "A cautious slip: short prices on picks that have come in at least 7 times in 10 lately.",
  balanced: "A middle-ground slip: the day's strongest patterns, neither the safest nor the longest odds.",
  bolder: "A riskier slip: longer odds on picks whose recent form beats the price. Less likely to all land.",
};

function defaultCaption(body: Compose, selected: Leg[]): string {
  const slotWord = body.slot === "nightly" ? "Nightly" : body.slot === "tomorrow" ? "Tomorrow's" : "Today's";
  const combined = selected.reduce((t, l) => t * l.price, 1);
  const lines = [
    `${slotWord} Kalchas parlay`,
    STYLE_NATURE[body.style as Style] ?? STYLE_NATURE.balanced,
    "",
    `${selected.length} legs · combined ${combined.toFixed(2)}`,
    `A 10 stake returns ${(10 * combined).toFixed(2)}`,
  ];
  if (body.slot === "nightly") lines.push("00:00–07:00 GMT+3");
  lines.push("", "kalchas.live", "For research & football enthusiast purposes only");
  return lines.join("\n");
}

export function AdminParlay({ api }: { api: Api }) {
  const [slot, setSlot] = useState<Slot>("today");
  const [style, setStyle] = useState<Style>("balanced");
  const [wanted, setWanted] = useState(5);
  const [exclude, setExclude] = useState<string[]>([]);
  const [pool, setPool] = useState<Compose | null>(null);
  const [generated, setGenerated] = useState<Compose | null>(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [advice, setAdvice] = useState("");
  const [evaluating, setEvaluating] = useState(false);
  const [evalError, setEvalError] = useState("");
  const [channels, setChannels] = useState<Record<string, boolean>>({
    x: true,
    telegram_free: true,
    telegram_paid: false,
    discord_free: true,
    discord_paid: false,
  });
  const [autopost, setAutopost] = useState(true);
  const [caption, setCaption] = useState("");
  const [postLog, setPostLog] = useState<PostLog | null>(null);

  const styleInfo = STYLES.find((s) => s.key === style) ?? STYLES[1];

  const loadPool = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const q = new URLSearchParams({ slot, style, legs: String(wanted) });
      const next = await api<Compose>(`/api/admin/parlay?${q}`);
      setPool(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "load failed");
      setPool(null);
    } finally {
      setBusy(false);
    }
  }, [api, slot, style, wanted]);

  useEffect(() => {
    void loadPool();
  }, [loadPool]);

  useEffect(() => {
    setExclude([]);
    setGenerated(null);
    setAdvice("");
    setPostLog(null);
    setCaption("");
    setPreviewUrl((old) => {
      if (old) URL.revokeObjectURL(old);
      return null;
    });
  }, [slot]);

  const most = pool?.available ?? 0;
  const n = Math.max(Math.min(wanted, most), Math.min(3, most));

  const draftSelected = useMemo(() => {
    if (!pool || pool.status !== "ready") return [] as Leg[];
    const byId = new Map(pool.legs.map((l) => [l.match_id, l]));
    const order = pool.order?.[style] ?? [];
    const dropped = new Set(exclude);
    return order
      .filter((id) => !dropped.has(id))
      .slice(0, n)
      .map((id) => byId.get(id))
      .filter((l): l is Leg => Boolean(l))
      .sort((a, b) => a.kickoff.localeCompare(b.kickoff) || a.match_id.localeCompare(b.match_id));
  }, [pool, style, exclude, n]);

  const selected = useMemo(() => generated?.selected ?? [], [generated]);
  const selectedIds = useMemo(() => selected.map((l) => l.match_id), [selected]);
  const combined = selected.reduce((t, l) => t * l.price, 1);

  async function generate() {
    setBusy(true);
    setError("");
    setStatus("");
    setAdvice("");
    setPostLog(null);
    try {
      const q = new URLSearchParams({ slot, style, legs: String(n) });
      if (exclude.length) q.set("exclude", exclude.join(","));
      const next = await api<Compose>(`/api/admin/parlay?${q}`);
      setGenerated(next);
      setPool(next);
      setCaption(defaultCaption(next, next.selected));
      setStatus("Slip generated.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "generate failed");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (!generated || !generated.can_post) {
      setPreviewUrl((old) => {
        if (old) URL.revokeObjectURL(old);
        return null;
      });
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      try {
        const res = await fetch("/api/admin/parlay/preview", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            slot,
            style,
            legs: generated.wanted,
            match_ids: selectedIds,
            exclude,
          }),
        });
        if (!res.ok) throw new Error(`preview HTTP ${res.status}`);
        const url = URL.createObjectURL(await res.blob());
        if (cancelled) {
          URL.revokeObjectURL(url);
          return;
        }
        setPreviewUrl((old) => {
          if (old) URL.revokeObjectURL(old);
          return url;
        });
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "preview failed");
      }
    }, 350);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [generated, slot, style, selectedIds, exclude]);

  function remove(id: string) {
    const floor = generated?.min_legs ?? pool?.min_legs ?? 3;
    const current = generated?.selected ?? draftSelected;
    if (current.length <= floor) return;
    setExclude((prev) => (prev.includes(id) ? prev : [...prev, id]));
    setGenerated(null);
    setAdvice("");
    setPostLog(null);
  }

  async function evaluate() {
    if (!generated) return;
    setBusy(true);
    setEvaluating(true);
    setEvalError("");
    setAdvice("");
    setError("");
    setStatus("");
    try {
      const res = await api<{ ok: boolean; advice: string }>("/api/admin/parlay/evaluate", {
        method: "POST",
        body: JSON.stringify({
          slot,
          style,
          legs: generated.wanted,
          match_ids: selectedIds,
          exclude,
        }),
      });
      setAdvice(res.advice);
      setStatus("Claude evaluated the slip.");
    } catch (err) {
      setEvalError(err instanceof Error ? err.message : "evaluate failed");
    } finally {
      setBusy(false);
      setEvaluating(false);
    }
  }

  async function post() {
    if (!generated) return;
    setBusy(true);
    setError("");
    setStatus("");
    try {
      const res = await api<{ ok: boolean; post_log: PostLog }>("/api/admin/parlay/post", {
        method: "POST",
        body: JSON.stringify({
          slot,
          style,
          legs: generated.wanted,
          match_ids: selectedIds,
          exclude,
          channels,
          caption,
          x_text: caption,
          autopost,
        }),
      });
      setPostLog(res.post_log);
      setStatus(res.ok ? "Posted to selected channels." : "Some channels failed — see log.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "post failed");
    } finally {
      setBusy(false);
    }
  }

  const showDraft = pool?.status === "ready";
  const showSlip = Boolean(generated && generated.status === "ready" && selected.length >= 3);

  return (
    <div className="ap">
      <div className="ap-bar kit-card">
        <div className="ap-slots" role="group" aria-label="Slot">
          {SLOTS.map((s) => (
            <button key={s.key} type="button" className={slot === s.key ? "is-on" : ""} onClick={() => setSlot(s.key)}>
              {s.label}
            </button>
          ))}
        </div>
        <div className="kit-card-right">
          {pool ? <span className="kit-muted">{dayLabel(pool.day)}</span> : null}
          <button type="button" className="kit-btn" disabled={busy || exclude.length === 0} onClick={() => setExclude([])}>
            Reset removals
          </button>
        </div>
      </div>

      {slot === "nightly" ? (
        <p className="kit-note ap-note">
          Nightly is admin-only. Kick-offs 00:00–07:00 GMT+3. Same priced-leg builder as public /parlay, filtered to that
          window.
        </p>
      ) : null}

      {error ? <p className="kit-error">{error}</p> : null}
      {status ? <p className="kit-muted ap-status">{status}</p> : null}
      {!pool && !error ? <p className="kit-empty">Loading…</p> : null}

      {pool && pool.status !== "ready" ? (
        <div className="kit-card ap-empty">
          <h2>{pool.status === "preparing" ? "Still preparing" : "No parlay for this slot"}</h2>
          <p>
            {pool.status === "preparing"
              ? "The watchlist for this day is still being built."
              : slot === "nightly"
                ? "No priced legs between 00:00 and 07:00 GMT+3."
                : "No priced strong picks for this day."}
          </p>
        </div>
      ) : null}

      {showDraft ? (
        <div className="kit-card ap-ctl">
          <div className="ap-cap">Choices · same logic as public /parlay</div>
          <div className="ap-ctl-row">
            <span className="ap-field">
              <label id="ap-n">Legs</label>
              <span className="ap-stepper" role="group" aria-labelledby="ap-n">
                <button type="button" disabled={n <= 3 || busy} onClick={() => setWanted(n - 1)} aria-label="One leg fewer">
                  −
                </button>
                <b aria-live="polite">{n}</b>
                <button type="button" disabled={n >= most || busy} onClick={() => setWanted(n + 1)} aria-label="One leg more">
                  +
                </button>
              </span>
            </span>
            <span className="ap-field">
              <label>Quick</label>
              <span className="ap-slots" role="group" aria-label="Number of legs">
                {PRESETS.map((p) => (
                  <button
                    key={p}
                    type="button"
                    className={n === p ? "is-on" : ""}
                    disabled={p > most || busy}
                    onClick={() => setWanted(p)}
                  >
                    {p}
                  </button>
                ))}
              </span>
            </span>
            <span className="ap-field">
              <label>Style</label>
              <span className="ap-slots" role="group" aria-label="Style">
                {STYLES.map((s) => (
                  <button
                    key={s.key}
                    type="button"
                    className={style === s.key ? "is-on" : ""}
                    disabled={busy}
                    onClick={() => setStyle(s.key)}
                  >
                    {s.label}
                  </button>
                ))}
              </span>
            </span>
          </div>
          <p className="ap-desc">
            {styleInfo.desc}
            {most < 18 ? ` Up to ${most} legs in this style on this day.` : ""}
          </p>
          <div className="ap-actions">
            <button type="button" className="kit-btn is-primary" disabled={busy || most < 3} onClick={() => void generate()}>
              Generate slip
            </button>
            <span className="kit-muted">
              Draft would take {draftSelected.length} legs
              {draftSelected.length ? ` · ~${draftSelected.reduce((t, l) => t * l.price, 1).toFixed(2)}` : ""}
            </span>
          </div>
        </div>
      ) : null}

      {showSlip ? (
        <div className="ap-grid">
          <div className="ap-legs">
            <div className="ap-cap">Generated slip · remove a leg you disagree with, then Generate again</div>
            <p className="ap-explain">{generated?.explanation}</p>
            <ol className="ap-list">
              {selected.map((leg, i) => (
                <li key={leg.match_id}>
                  <div className="ap-leg">
                    <span className="ap-n">{String(i + 1).padStart(2, "0")}</span>
                    <div className="ap-leg-body">
                      <b>
                        {leg.home.name} v {leg.away.name}
                      </b>
                      <span>
                        {kickHm(leg.kickoff)} · {leg.label} · {leg.hit}/{leg.n} recent · {leg.price.toFixed(2)}
                      </span>
                      {leg.brief ? <span className="ap-brief">{leg.brief}</span> : null}
                    </div>
                    <button
                      type="button"
                      className="kit-btn"
                      disabled={selected.length <= (generated?.min_legs ?? 3) || busy}
                      onClick={() => remove(leg.match_id)}
                    >
                      Remove
                    </button>
                  </div>
                </li>
              ))}
            </ol>
            <div className="ap-sum">
              <span>
                {selected.length} legs · combined <b>{combined.toFixed(2)}</b> · {oneIn(combined)}
              </span>
              <span>
                Stake 10 returns <b>{(10 * combined).toFixed(2)}</b>
              </span>
            </div>

            <div className="ap-claude kit-card">
              <div className="ap-cap">Evaluate by Claude</div>
              <p className="kit-muted">
                Finds a weak point or a quieter swap from unused candidates. Does not change the slip.
              </p>
              <button
                type="button"
                className="kit-btn"
                disabled={busy || !(generated?.claude_ready ?? true)}
                onClick={() => void evaluate()}
              >
                {evaluating ? "Claude is reading the slip…" : "Evaluate by Claude"}
              </button>
              {!(generated?.claude_ready ?? true) ? (
                <p className="kit-error">ANTHROPIC_API_KEY is not available on the API.</p>
              ) : null}
              {evalError ? <p className="kit-error">{evalError}</p> : null}
              {advice ? <pre className="ap-advice">{advice}</pre> : null}
            </div>

            <div className="ap-share kit-card">
              <div className="ap-cap">Share</div>
              <div className="ap-channels">
                {CHANNELS.map((ch) => (
                  <label key={ch.key}>
                    <input
                      type="checkbox"
                      checked={Boolean(channels[ch.key])}
                      disabled={busy}
                      onChange={(e) => setChannels((c) => ({ ...c, [ch.key]: e.target.checked }))}
                    />
                    {ch.label}
                  </label>
                ))}
              </div>
              <label className="ap-auto">
                <input type="checkbox" checked={autopost} disabled={busy} onChange={(e) => setAutopost(e.target.checked)} />
                Autopost counterpost when settled
              </label>
              <label className="ap-caption-label">
                Caption
                <textarea rows={5} value={caption} disabled={busy} onChange={(e) => setCaption(e.target.value)} />
              </label>
              <button
                type="button"
                className="kit-btn is-primary"
                disabled={busy || !Object.values(channels).some(Boolean)}
                onClick={() => void post()}
              >
                Post to selected channels
              </button>
              {postLog ? (
                <div className="ap-log">
                  {CHANNELS.filter((ch) => postLog[ch.key]).map((ch) => {
                    const entry = postLog[ch.key];
                    return (
                      <span key={ch.key} className={`kit-pill ${entry.ok ? "is-ok" : "is-miss"}`} title={entry.error}>
                        {entry.ok ? "✓" : "✗"} {ch.label}
                      </span>
                    );
                  })}
                </div>
              ) : null}
            </div>
          </div>

          <div className="ap-preview">
            <div className="ap-cap">Thermal slip</div>
            {previewUrl ? (
              <a href={previewUrl} target="_blank" rel="noreferrer">
                <img src={previewUrl} alt="Parlay slip preview" />
              </a>
            ) : (
              <div className="ap-ph">Rendering…</div>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}
