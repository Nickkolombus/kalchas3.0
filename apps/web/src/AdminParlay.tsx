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
  day: string;
  today: string;
  status: "ready" | "preparing" | "none";
  window_label: string | null;
  stake: number;
  min_legs: number;
  legs: Leg[];
  order: Record<Style, string[]>;
  selected: Leg[];
  combined: number | null;
  returns: number | null;
  can_post: boolean;
  exclude: string[];
};

const SLOTS: { key: Slot; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "tomorrow", label: "Tomorrow" },
  { key: "nightly", label: "Nightly" },
];

const STYLES: { key: Style; label: string }[] = [
  { key: "safer", label: "Safer" },
  { key: "balanced", label: "Balanced" },
  { key: "bolder", label: "Bolder" },
];

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

export function AdminParlay({ api }: { api: Api }) {
  const [slot, setSlot] = useState<Slot>("today");
  const [style, setStyle] = useState<Style>("balanced");
  const [exclude, setExclude] = useState<string[]>([]);
  const [body, setBody] = useState<Compose | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  const excludeQuery = exclude.join(",");

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const q = new URLSearchParams({ slot, style });
      if (excludeQuery) q.set("exclude", excludeQuery);
      setBody(await api<Compose>(`/api/admin/parlay?${q}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "load failed");
      setBody(null);
    } finally {
      setBusy(false);
    }
  }, [api, slot, style, excludeQuery]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    setExclude([]);
  }, [slot]);

  const selectedIds = useMemo(() => (body?.selected ?? []).map((l) => l.match_id), [body]);

  useEffect(() => {
    if (!body || !body.can_post) {
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
          body: JSON.stringify({ slot, style, match_ids: selectedIds, exclude }),
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
    }, 400);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [body, slot, style, selectedIds, exclude]);

  function remove(id: string) {
    if (!body || body.selected.length <= body.min_legs) return;
    setExclude((prev) => (prev.includes(id) ? prev : [...prev, id]));
  }

  function resetLegs() {
    setExclude([]);
  }

  const selected = body?.selected ?? [];
  const pool = body?.legs ?? [];

  return (
    <div className="ap">
      <div className="ap-bar kit-card">
        <div className="ap-slots" role="group" aria-label="Slot">
          {SLOTS.map((s) => (
            <button
              key={s.key}
              type="button"
              className={slot === s.key ? "is-on" : ""}
              onClick={() => setSlot(s.key)}
            >
              {s.label}
            </button>
          ))}
        </div>
        <div className="ap-slots" role="group" aria-label="Style">
          {STYLES.map((s) => (
            <button
              key={s.key}
              type="button"
              className={style === s.key ? "is-on" : ""}
              onClick={() => setStyle(s.key)}
            >
              {s.label}
            </button>
          ))}
        </div>
        <div className="kit-card-right">
          {body ? <span className="kit-muted">{dayLabel(body.day)}</span> : null}
          <button type="button" className="kit-btn" disabled={busy || exclude.length === 0} onClick={resetLegs}>
            Reset legs
          </button>
        </div>
      </div>

      {slot === "nightly" ? (
        <p className="kit-note ap-note">
          Nightly is admin-only. Kick-offs 00:00–07:00 GMT+3 (LATAM evening for Europe). Not on the public /parlay page.
        </p>
      ) : null}

      {error ? <p className="kit-error">{error}</p> : null}
      {!body && !error ? <p className="kit-empty">Loading…</p> : null}

      {body && body.status !== "ready" ? (
        <div className="kit-card ap-empty">
          <h2>{body.status === "preparing" ? "Still preparing" : "No parlay for this slot"}</h2>
          <p>
            {body.status === "preparing"
              ? "The watchlist for this day is still being built. Check back in a few minutes."
              : slot === "nightly"
                ? "No priced legs with kick-off between 00:00 and 07:00 GMT+3 on this day."
                : "No priced strong picks for this day."}
          </p>
        </div>
      ) : null}

      {body && body.status === "ready" ? (
        <div className="ap-grid">
          <div className="ap-legs">
            <div className="ap-cap">
              Legs · remove any you disagree with (floor {body.min_legs})
            </div>
            {selected.length === 0 ? <p className="kit-empty">No legs left in this style.</p> : null}
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
                    </div>
                    <button
                      type="button"
                      className="kit-btn"
                      disabled={selected.length <= body.min_legs}
                      onClick={() => remove(leg.match_id)}
                    >
                      Remove
                    </button>
                  </div>
                </li>
              ))}
            </ol>
            {exclude.length ? (
              <p className="kit-muted ap-removed">
                Removed {exclude.length}. Pool still has {pool.length} priced legs for this slot.
              </p>
            ) : null}
            <div className="ap-sum">
              <span>
                {selected.length} legs · combined <b>{body.combined?.toFixed(2) ?? "—"}</b>
              </span>
              <span>
                Stake {body.stake.toFixed(0)} returns <b>{body.returns?.toFixed(2) ?? "—"}</b>
              </span>
            </div>
            <p className="kit-muted">
              Phase 1–2: compose and thermal preview. Channel post and counterpost come next.
            </p>
          </div>

          <div className="ap-preview">
            <div className="ap-cap">Thermal slip · updates as you edit</div>
            {previewUrl ? (
              <a href={previewUrl} target="_blank" rel="noreferrer">
                <img src={previewUrl} alt="Parlay slip preview" />
              </a>
            ) : (
              <div className="ap-ph">
                {body.can_post ? "Rendering…" : `Need at least ${body.min_legs} legs`}
              </div>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}
