import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AdminParlayPosted, CHANNELS } from "./AdminParlayPosted";
import {
  Crest,
  PARLAY_MIN,
  PARLAY_PRESETS,
  PARLAY_STYLES,
  Record,
  clock,
  oneIn,
  pickParlay,
  plural,
  type ParlayDay,
  type ParlayLeg,
  type ParlayStyle,
} from "./Watchlist";

/* Admin parlay: the public /parlay builder, plus the admin's edits, Claude's
   read, a review step and the posted slips. The day comes in one request and
   the slip is built here with the public page's own pickParlay, so every
   control is instant and the slip is exactly what a visitor would see, until
   the admin edits it. */

type Api = <T>(path: string, init?: RequestInit) => Promise<T>;
type Slot = "today" | "tomorrow" | "nightly";

type AdminDay = ParlayDay & {
  slot: Slot;
  window_label: string | null;
  stake: number;
  max_legs: number;
  claude_ready: boolean;
};

type Suggestion = {
  kind: "swap" | "remove" | "add";
  remove: string | null;
  add: string | null;
  remove_label: string | null;
  add_label: string | null;
  why: string;
};

type Advice = { key: string; advice: string; suggestions: Suggestion[]; model?: string };

const MAX_LEGS = 18;

const SLOTS: { key: Slot; label: string; hint: string }[] = [
  { key: "today", label: "Today", hint: "Today's watchlist, as on the public page." },
  { key: "tomorrow", label: "Tomorrow", hint: "Tomorrow's watchlist, as on the public page." },
  { key: "nightly", label: "Nightly", hint: "Kick-offs 00:00–07:00 GMT+3 only. Admin-only." },
];


/* Two builders share this page. "priced" is the public slip: legs we hold a
   bookmaker price for. "any" takes each match's strongest pattern whatever the
   market; we hold a price for only some of those, so each leg has an odds box
   and the slip can be posted once every box is filled. A leg still waiting
   for odds carries price 0 here. */
type Kind = "priced" | "any";

type LegRef = { match_id: string; market: string; price: number | null };

const hasPrice = (l: ParlayLeg) => l.price > 1;

const refsOf = (legs: ParlayLeg[]): LegRef[] =>
  legs.map((l) => ({ match_id: l.match_id, market: l.market, price: hasPrice(l) ? l.price : null }));

/** Odds as typed, "1.85" or "1,85". Null until it reads as a price above 1. */
function typedOdds(raw: string): number | null {
  const n = Number(raw.trim().replace(",", "."));
  return Number.isFinite(n) && n > 1 && n <= 1000 ? Math.round(n * 100) / 100 : null;
}

/** POST that keeps the server's structured detail (a 409 lists what changed). */
async function post(path: string, body: unknown): Promise<Response> {
  return fetch(path, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function problem(res: Response): Promise<{ message: string; changes: string[] }> {
  const body = (await res.json().catch(() => ({}))) as { detail?: unknown };
  const d = body.detail;
  if (d && typeof d === "object" && "message" in d) {
    const o = d as { message: string; changes?: string[] };
    return { message: o.message, changes: o.changes ?? [] };
  }
  return { message: typeof d === "string" ? d : `HTTP ${res.status}`, changes: [] };
}

export function AdminParlay({ api }: { api: Api }) {
  const [tab, setTab] = useState<"build" | "any" | "posted">("build");
  const [postedTick, setPostedTick] = useState(0);
  return (
    <div className="ap wl-vars">
      <div className="ap-tabs" role="tablist">
        <button type="button" role="tab" aria-selected={tab === "build"} className={tab === "build" ? "on" : ""} onClick={() => setTab("build")}>
          Build a slip
        </button>
        <button type="button" role="tab" aria-selected={tab === "any"} className={tab === "any" ? "on" : ""} onClick={() => setTab("any")}>
          Any-market slip
        </button>
        <button type="button" role="tab" aria-selected={tab === "posted"} className={tab === "posted" ? "on" : ""} onClick={() => setTab("posted")}>
          Posted slips
        </button>
      </div>
      {tab !== "posted" ? (
        <Builder
          key={tab}
          kind={tab === "any" ? "any" : "priced"}
          api={api}
          onSaved={() => {
            setPostedTick((t) => t + 1);
            setTab("posted");
          }}
        />
      ) : (
        <AdminParlayPosted api={api} refresh={postedTick} />
      )}
    </div>
  );
}

function Builder({ api, kind, onSaved }: { api: Api; kind: Kind; onSaved: () => void }) {
  const any = kind === "any";
  const [slot, setSlot] = useState<Slot>("today");
  const [style, setStyle] = useState<ParlayStyle>("balanced");
  const [wanted, setWanted] = useState(5);
  const [removed, setRemoved] = useState<string[]>([]);
  const [pinned, setPinned] = useState<string[]>([]);
  // Any-market slip: what the admin typed in each leg's odds box, by match.
  const [typed, setTyped] = useState<Record<string, string>>({});
  const [day, setDay] = useState<AdminDay | null>(null);
  const [loadError, setLoadError] = useState("");
  const [loading, setLoading] = useState(false);
  const [note, setNote] = useState("");

  const load = useCallback(
    async (which: Slot) => {
      setLoading(true);
      setLoadError("");
      try {
        const got = await api<AdminDay>(`/api/admin/parlay/day?slot=${which}${any ? "&kind=any" : ""}`);
        // A pick we hold no price for comes as null; here that is price 0.
        setDay(any ? { ...got, legs: got.legs.map((l) => ({ ...l, price: l.price ?? 0 })) } : got);
      } catch (e) {
        setLoadError(e instanceof Error ? e.message : "Could not load the list");
      } finally {
        setLoading(false);
      }
    },
    [api, any],
  );

  useEffect(() => {
    void load(slot);
  }, [load, slot]);

  const pickSlot = (s: Slot) => {
    if (s === slot) return;
    setSlot(s);
    setDay(null);
    setRemoved([]);
    setPinned([]);
    setTyped({});
    setNote("");
  };

  // The any-market list has one order (every style carries it), so style stays put.
  const base = pickParlay(day, style, wanted, { removed, pinned });
  const { n, most } = base;
  const held = new Map(base.legs.map((l) => [l.match_id, l.price]));
  // What is in the box wins over the price we hold, also when it is cleared.
  const legs = any
    ? base.legs.map((l) => (l.match_id in typed ? { ...l, price: typedOdds(typed[l.match_id]) ?? 0 } : l))
    : base.legs;
  const missing = legs.filter((l) => !hasPrice(l)).length;
  const odds = legs.reduce((t, l) => t * (hasPrice(l) ? l.price : 1), 1);
  const looks = legs.filter((l) => l.watch === "look").length;
  const chosen = new Set(legs.map((l) => l.match_id));
  const styleInfo = PARLAY_STYLES.find((s) => s.key === style) ?? PARLAY_STYLES[1];
  const edited = removed.length + pinned.length > 0;
  const ready = day?.status === "ready";

  // Legs on offer but not on the slip: this style's order first, then legs
  // below its bar (an admin may still want one).
  const spare = useMemo(() => {
    if (!day) return [] as { leg: ParlayLeg; below: boolean }[];
    const inOrder = new Set(day.order[style]);
    const byId = new Map(day.legs.map((l) => [l.match_id, l]));
    const first = day.order[style].filter((id) => !chosen.has(id)).map((id) => byId.get(id)!);
    const rest = day.legs.filter((l) => !inOrder.has(l.match_id) && !chosen.has(l.match_id)).sort((a, b) => b.score - a.score);
    return [...first.map((leg) => ({ leg, below: false })), ...rest.map((leg) => ({ leg, below: true }))];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [day, style, legs.map((l) => l.match_id).join(",")]);

  const remove = (id: string) => {
    const leg = legs.find((l) => l.match_id === id);
    setPinned((p) => p.filter((x) => x !== id));
    setRemoved((r) => (r.includes(id) ? r : [...r, id]));
    if (n > PARLAY_MIN) {
      setWanted(n - 1);
      setNote(`Removed ${leg ? `${leg.home.name} v ${leg.away.name}` : "the leg"}.`);
    } else {
      setNote(`Removed. A slip needs ${PARLAY_MIN} legs, so the next one in ${styleInfo.name} order took its place.`);
    }
  };

  const add = (id: string) => {
    if (n >= MAX_LEGS) return;
    setRemoved((r) => r.filter((x) => x !== id));
    setPinned((p) => (p.includes(id) ? p : [...p, id]));
    setWanted(n + 1);
    const leg = day?.legs.find((l) => l.match_id === id);
    setNote(`Added ${leg ? `${leg.home.name} v ${leg.away.name}` : "the leg"}.`);
  };

  const apply = (s: Suggestion) => {
    if (s.remove) {
      setPinned((p) => p.filter((x) => x !== s.remove));
      setRemoved((r) => (r.includes(s.remove!) ? r : [...r, s.remove!]));
    }
    if (s.add) {
      setRemoved((r) => r.filter((x) => x !== s.add));
      setPinned((p) => (p.includes(s.add!) ? p : [...p, s.add!]));
    }
    if (s.kind === "add") setWanted(Math.min(MAX_LEGS, n + 1));
    if (s.kind === "remove") setWanted(Math.max(PARLAY_MIN, n - 1));
    setNote(
      s.kind === "swap"
        ? `Swapped ${s.remove_label} for ${s.add_label}.`
        : s.kind === "add"
          ? `Added ${s.add_label}.`
          : `Removed ${s.remove_label}.`,
    );
  };

  const reset = () => {
    setRemoved([]);
    setPinned([]);
    setNote("Back to the plain " + styleInfo.name.toLowerCase() + " slip.");
  };

  const what = any ? "any-market parlay" : "parlay";
  const title = slot === "today" ? `Today's ${what}` : slot === "tomorrow" ? `Tomorrow's ${what}` : `Nightly ${what}`;
  const slotHint = SLOTS.find((s) => s.key === slot)!.hint;

  return (
    <>
      <div className="kit-card ap-head">
        <div className="kit-card-head">
          <h2>{title}</h2>
          <span className="kit-sub">
            {day ? longDate(day.day) : ""}
            {day?.window_label ? ` · ${day.window_label}` : ""}
          </span>
          <div className="kit-card-right">
            <span className="wl-seg" role="group" aria-label="Slot">
              {SLOTS.map((s) => (
                <button key={s.key} type="button" className={slot === s.key ? "on" : ""} aria-pressed={slot === s.key} onClick={() => pickSlot(s.key)}>
                  {s.label}
                </button>
              ))}
            </span>
          </div>
        </div>
        {any ? (
          <p className="kit-card-body kit-sub ap-lede">
            {slotHint} Each match offers its strongest pattern, whatever the market: late goals, cards, corners, a team to
            score, as well as the usual goals and both-teams-score picks. Where we hold a bookmaker price it is already in
            the odds box and you can type over it; where we don't, the box is empty. The slip can be posted once every
            leg has odds.
          </p>
        ) : (
          <p className="kit-card-body kit-sub ap-lede">
            {slotHint} The slip starts as the public builder makes it; remove what you don't agree with, add from the legs
            on offer, then review and post. Every leg keeps the price you see: if the list moves before you post, you're
            told what changed.
          </p>
        )}
      </div>

      <div className="ap-grid">
        <div className="wl-card ap-build">
          {loading && !day ? <p className="wl-empty">Loading…</p> : null}
          {loadError ? <p className="wl-empty">The list is unavailable: {loadError}</p> : null}
          {day?.status === "preparing" ? <p className="wl-empty">This day's list is still being put together. Try again in a few minutes.</p> : null}
          {day?.status === "none" ? <p className="wl-empty">No watchlist for {longDate(day.day)}.</p> : null}
          {ready && most < PARLAY_MIN ? (
            <p className="wl-empty">
              Not enough {any ? "picks" : "priced picks"} {slot === "nightly" ? "in the night window" : "on this day"} for a slip of {PARLAY_MIN}.
            </p>
          ) : null}

          {ready && most >= PARLAY_MIN ? (
            <>
              <div className="wl-par-sum">
                <div className="wl-par-big">
                  <small>{plural(legs.length, "leg")} · combined odds</small>
                  <b>{missing ? "—" : odds.toFixed(2)}</b>
                </div>
                {missing ? (
                  <p>
                    {missing === legs.length
                      ? "None of the legs has odds yet."
                      : `${plural(missing, "leg")} still ${missing === 1 ? "needs" : "need"} odds.`}{" "}
                    Type them in the boxes: the combined odds show, and the slip can be posted, once every leg has odds
                    above 1.00.
                  </p>
                ) : (
                  <p>
                    All {legs.length} have to land. At these prices {any ? "that is rated" : "bookmakers rate that"} {oneIn(odds)}. Each
                    leg shows how often it happened in the two teams' recent games.
                    {looks ? ` ${plural(looks, "leg")} from Worth a look.` : ""}
                  </p>
                )}
                <div className="wl-par-big is-side">
                  <small>A 10 stake returns</small>
                  <b>{missing ? "—" : (10 * odds).toFixed(2)}</b>
                </div>
              </div>

              <div className="wl-par-ctl">
                <span className="wl-par-field">
                  <label id="ap-n">Legs</label>
                  <span className="wl-stepper-n" role="group" aria-labelledby="ap-n">
                    <button type="button" disabled={n <= PARLAY_MIN} onClick={() => setWanted(n - 1)} aria-label="One leg fewer">
                      −
                    </button>
                    <b aria-live="polite">{n}</b>
                    <button type="button" disabled={n >= Math.min(most, MAX_LEGS)} onClick={() => setWanted(n + 1)} aria-label="One leg more">
                      +
                    </button>
                  </span>
                </span>
                <span className="wl-par-field">
                  <label>Quick</label>
                  <span className="wl-seg" role="group" aria-label="Number of legs">
                    {PARLAY_PRESETS.map((p) => (
                      <button key={p} type="button" className={n === p ? "on" : ""} aria-pressed={n === p} disabled={p > most} onClick={() => setWanted(p)}>
                        {p}
                      </button>
                    ))}
                  </span>
                </span>
                {any ? null : (
                  <span className="wl-par-field">
                    <label>Style</label>
                    <span className="wl-seg" role="group" aria-label="Style">
                      {PARLAY_STYLES.map((s) => (
                        <button key={s.key} type="button" className={style === s.key ? "on" : ""} aria-pressed={style === s.key} onClick={() => setStyle(s.key)}>
                          {s.name}
                        </button>
                      ))}
                    </span>
                  </span>
                )}
                <p className="wl-par-desc">
                  {any ? "Each match's strongest pattern, strong matches first, in the order the watchlist ranks them." : styleInfo.desc}
                  {most < MAX_LEGS ? ` Up to ${most} legs ${any ? "today" : "in this style"}${edited ? " with your edits" : ""}.` : ""}
                </p>
              </div>

              {edited || note ? (
                <div className="ap-edits" aria-live="polite">
                  <span>
                    {note}
                    {edited ? ` ${editSummary(removed.length, pinned.length)}` : ""}
                  </span>
                  {edited ? (
                    <button type="button" className="kit-link" onClick={reset}>
                      Reset edits
                    </button>
                  ) : null}
                </div>
              ) : null}

              <ol className="wl-legs">
                {legs.map((l, i) => (
                  <li key={l.match_id}>
                    <div className={`wl-leg ap-leg${any ? " is-any" : ""}${pinned.includes(l.match_id) ? " is-pinned" : ""}`}>
                      <span className="wl-leg-n">{i + 1}</span>
                      <span className="wl-leg-time">{clock(l.kickoff)}</span>
                      <span className="wl-leg-body">
                        <span className="wl-leg-match">
                          <Crest src={l.home.badge} name={l.home.name} size={16} />
                          <span>
                            {l.home.name} v {l.away.name}
                          </span>
                          <small>{l.league}</small>
                        </span>
                        <span className="wl-leg-mkt">
                          {l.label}
                          {l.watch === "look" ? <small> · Worth a look</small> : null}
                          {pinned.includes(l.match_id) ? <small className="ap-tag"> · added by you</small> : null}
                          {any && !((held.get(l.match_id) ?? 0) > 1) ? <small> · we hold no price</small> : null}
                        </span>
                        <span className="wl-leg-why">{l.brief}</span>
                      </span>
                      {l.n ? <Record leg={l} /> : <span className="wl-rec" />}
                      {any ? (
                        <input
                          className={`ap-odds${hasPrice(l) ? "" : " is-need"}`}
                          inputMode="decimal"
                          placeholder="odds"
                          aria-label={`Odds for ${l.home.name} v ${l.away.name}, ${l.label}`}
                          value={typed[l.match_id] ?? ((held.get(l.match_id) ?? 0) > 1 ? held.get(l.match_id)!.toFixed(2) : "")}
                          onChange={(e) => setTyped((t) => ({ ...t, [l.match_id]: e.target.value }))}
                        />
                      ) : (
                        <span className="wl-leg-price">{l.price.toFixed(2)}</span>
                      )}
                      <button type="button" className="ap-x" title="Remove this leg" aria-label={`Remove ${l.home.name} v ${l.away.name}`} onClick={() => remove(l.match_id)}>
                        ×
                      </button>
                    </div>
                  </li>
                ))}
              </ol>

              {spare.length ? (
                <details className="wl-par-out ap-spare">
                  <summary>More legs on offer ({spare.length})</summary>
                  <ul>
                    {spare.map(({ leg: l, below }) => (
                      <li key={l.match_id}>
                        <span className="ap-spare-time">{clock(l.kickoff)}</span>
                        <span className="ap-spare-body">
                          <b>
                            {l.home.name} v {l.away.name}
                          </b>{" "}
                          · {l.label}
                          {l.watch === "look" ? " · Worth a look" : ""}
                          {removed.includes(l.match_id) ? <small className="ap-tag"> · removed by you</small> : null}
                          {below ? <small> · {any ? "further down the list" : `below the ${styleInfo.name.toLowerCase()} bar`}</small> : null}
                        </span>
                        {l.n ? <Record leg={l} /> : <span className="wl-rec" />}
                        <span className="wl-leg-price">{hasPrice(l) ? l.price.toFixed(2) : "—"}</span>
                        <button type="button" className="kit-btn" disabled={n >= MAX_LEGS} onClick={() => add(l.match_id)}>
                          Add
                        </button>
                      </li>
                    ))}
                  </ul>
                </details>
              ) : null}

              {day.unpriced.length ? (
                <details className="wl-par-out">
                  <summary>Strong picks with no price ({day.unpriced.length})</summary>
                  <ul>
                    {day.unpriced.map((m) => (
                      <li key={m.match_id}>
                        {m.home} v {m.away}: patterns ({m.tags.join(", ")}) have no bookmaker price we hold, so they can't be a leg.
                      </li>
                    ))}
                  </ul>
                </details>
              ) : null}

              <ClaudeRead
                slot={slot}
                style={style}
                kind={kind}
                legs={legs}
                ready={day.claude_ready}
                onApply={apply}
              />
            </>
          ) : null}
        </div>

        {ready && legs.length >= PARLAY_MIN ? (
          <Review slot={slot} style={style} kind={kind} legs={legs} missing={missing} onReload={() => void load(slot)} onSaved={onSaved} />
        ) : null}
      </div>
    </>
  );
}

function editSummary(removed: number, added: number): string {
  const bits = [];
  if (removed) bits.push(`${removed} removed`);
  if (added) bits.push(`${added} added`);
  return `(${bits.join(", ")} by you)`;
}

function longDate(iso: string): string {
  const at = new Date(`${iso}T12:00:00`);
  if (Number.isNaN(at.getTime())) return iso;
  return at.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
}

/* ------------------------------------------------------------- Claude */

function ClaudeRead({
  slot,
  style,
  kind,
  legs,
  ready,
  onApply,
}: {
  slot: Slot;
  style: ParlayStyle;
  kind: Kind;
  legs: ParlayLeg[];
  ready: boolean;
  onApply: (s: Suggestion) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [read, setRead] = useState<Advice | null>(null);
  const key = `${slot}|${style}|${legs.map((l) => `${l.match_id}@${l.price}`).join(",")}`;
  const stale = read !== null && read.key !== key;

  const ask = async () => {
    setBusy(true);
    setError("");
    try {
      const res = await post("/api/admin/parlay/evaluate", { slot, style, kind, legs: refsOf(legs) });
      if (!res.ok) throw new Error((await problem(res)).message);
      const body = (await res.json()) as Omit<Advice, "key">;
      setRead({ ...body, key });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Claude failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="ap-claude">
      <div className="ap-claude-head">
        <div>
          <b>Ask Claude</b>
          <span className="kit-sub"> · finds the weakest leg and better swaps among the legs on offer. It changes nothing by itself.</span>
        </div>
        <button type="button" className="kit-btn" disabled={busy || !ready} onClick={() => void ask()}>
          {busy ? "Claude is reading the slip…" : read ? "Ask again" : "Ask Claude"}
        </button>
      </div>
      {!ready ? <p className="kit-sub">ANTHROPIC_API_KEY isn't set on the API service.</p> : null}
      {error ? <p className="kit-error">{error}</p> : null}
      {read ? (
        <div className={stale ? "ap-claude-body is-stale" : "ap-claude-body"}>
          {stale ? <p className="ap-stale">The slip changed since Claude read it. Ask again for a fresh read.</p> : null}
          <div className="ap-advice">{read.advice}</div>
          {read.suggestions.length ? (
            <ul className="ap-suggest">
              {read.suggestions.map((s, i) => (
                <li key={i}>
                  <span>
                    {s.remove_label ? <span className="ap-minus">− {s.remove_label}</span> : null}
                    {s.add_label ? <span className="ap-plus">+ {s.add_label}</span> : null}
                    <small>{s.why}</small>
                  </span>
                  <button type="button" className="kit-btn" disabled={stale} onClick={() => onApply(s)}>
                    Apply
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------- review */

function Review({
  slot,
  style,
  kind,
  legs,
  missing,
  onReload,
  onSaved,
}: {
  slot: Slot;
  style: ParlayStyle;
  kind: Kind;
  legs: ParlayLeg[];
  /** Legs still waiting for odds: nothing is drawn or posted until it is 0. */
  missing: number;
  onReload: () => void;
  onSaved: () => void;
}) {
  const [image, setImage] = useState("");
  const [caption, setCaption] = useState("");
  const [captionEdited, setCaptionEdited] = useState(false);
  const [channels, setChannels] = useState<Record<string, boolean>>({ x: true, telegram_free: true });
  const [autopost, setAutopost] = useState(true);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ message: string; changes: string[] } | null>(null);
  const key = `${slot}|${style}|${legs.map((l) => `${l.match_id}@${l.price}`).join(",")}`;
  const last = useRef("");

  // The slip image follows the slip, a moment after it settles.
  useEffect(() => {
    setConfirming(false);
    if (missing) return;
    const timer = window.setTimeout(async () => {
      last.current = key;
      try {
        const res = await post("/api/admin/parlay/preview", { slot, style, kind, legs: refsOf(legs) });
        if (res.ok && last.current === key) {
          const url = URL.createObjectURL(await res.blob());
          setImage((old) => {
            if (old) URL.revokeObjectURL(old);
            return url;
          });
        }
      } catch {
        /* the preview is a nicety; saving checks everything again */
      }
    }, 350);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  // So does the default text, until the admin writes their own.
  useEffect(() => {
    if (captionEdited || missing) return;
    let live = true;
    const timer = window.setTimeout(async () => {
      try {
        const res = await post("/api/admin/parlay/caption", { slot, style, kind, legs: refsOf(legs) });
        if (res.ok && live) setCaption(((await res.json()) as { caption: string }).caption);
      } catch {
        /* the server writes the default again when saving an empty text */
      }
    }, 350);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, captionEdited]);

  const picked = CHANNELS.filter((c) => channels[c.key]);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await post("/api/admin/parlay/slips", {
        slot,
        style,
        kind,
        legs: refsOf(legs),
        caption,
        channels,
        autopost,
      });
      if (!res.ok) {
        setError(await problem(res));
        return;
      }
      onSaved();
    } catch (e) {
      setError({ message: e instanceof Error ? e.message : "Saving failed", changes: [] });
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  };

  return (
    <div className="kit-card ap-review">
      <div className="kit-card-head">
        <h2>Review and post</h2>
      </div>
      <div className="kit-card-body ap-review-body">
        <div className="ap-slip">
          {missing ? (
            <span className="kit-sub">
              {plural(missing, "leg")} still {missing === 1 ? "needs" : "need"} odds. The slip is drawn once every leg has them.
            </span>
          ) : image ? (
            <img src={image} alt="The slip as it will be posted" />
          ) : (
            <span className="kit-sub">Drawing the slip…</span>
          )}
        </div>

        <label className="ap-label" htmlFor="ap-caption">
          Post text
          {captionEdited ? (
            <button
              type="button"
              className="kit-link"
              onClick={() => setCaptionEdited(false)}
            >
              Use the default
            </button>
          ) : null}
        </label>
        <textarea
          id="ap-caption"
          rows={7}
          value={caption}
          onChange={(e) => {
            setCaption(e.target.value);
            setCaptionEdited(true);
          }}
        />
        <span className="kit-sub">X gets the first 280 characters.</span>

        <fieldset className="ap-channels">
          <legend>Post to</legend>
          {CHANNELS.map((c) => (
            <label key={c.key}>
              <input type="checkbox" checked={Boolean(channels[c.key])} onChange={(e) => setChannels({ ...channels, [c.key]: e.target.checked })} />
              {c.label}
            </label>
          ))}
        </fieldset>

        <label className="ap-check">
          <input type="checkbox" checked={autopost} onChange={(e) => setAutopost(e.target.checked)} />
          <span>
            Reply with the result automatically
            <small>
              Once every match is played, the slip comes back marked in ballpoint as a reply under each post. Unticked, the bot
              sends it to you on Telegram first. Called-off legs are always asked.
            </small>
          </span>
        </label>

        {error ? (
          <div className="ap-problem">
            <p className="kit-error">{error.message}</p>
            {error.changes.length ? (
              <>
                <ul>
                  {error.changes.map((c) => (
                    <li key={c}>{c}</li>
                  ))}
                </ul>
                <button type="button" className="kit-btn" onClick={onReload}>
                  Reload the list
                </button>
              </>
            ) : null}
          </div>
        ) : null}

        {confirming ? (
          <div className="ap-confirm">
            <p>
              Post this {plural(legs.length, "leg")} slip to {picked.map((c) => c.label).join(", ")}? It goes public within a
              minute.
            </p>
            <div>
              <button type="button" className="kit-btn is-primary" disabled={busy} onClick={() => void save()}>
                {busy ? "Saving…" : "Yes, post it"}
              </button>
              <button type="button" className="kit-btn" disabled={busy} onClick={() => setConfirming(false)}>
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <button type="button" className="kit-btn is-primary ap-post" disabled={!picked.length || !caption.trim() || missing > 0} onClick={() => setConfirming(true)}>
            {missing ? "Every leg needs odds first" : `Post to ${plural(picked.length, "channel")}…`}
          </button>
        )}
      </div>
    </div>
  );
}
