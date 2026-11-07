import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

type Api = <T>(path: string, init?: RequestInit) => Promise<T>;

type Kind = "week" | "day";
type Texts = Record<string, string>;
type Channels = Record<string, boolean>;

type FieldSpec = { key: string; label: string; where: string; rows: number; hint: string };

type Recap = {
  kind: Kind;
  week_start: string;
  status: "draft" | "approved" | "posting" | "posted" | "skipped" | "failed";
  editable: boolean;
  deadline: string | null;
  headline: string;
  texts: Texts;
  fields: FieldSpec[];
  needs_lesson: boolean;
  card_count: number;
  channels: Channels;
  post_log: Record<string, { ok: boolean; error?: string; ref?: string } | string>;
  notes: string[];
  posted_at: string | null;
  data?: { strategy_filter?: string[] };
};

type StrategyChoice = { key: string; name: string; short: string };

type Payload = {
  kind?: Kind;
  recap: Recap | null;
  weeks?: { week_start: string; status: string }[];
  last_week?: string;
  this_week?: string;
  today?: string;
  yesterday?: string;
  strategies?: StrategyChoice[];
};

const CHANNELS: [string, string][] = [
  ["x", "X"],
  ["telegram_free", "Telegram free"],
  ["telegram_paid", "Telegram paid"],
  ["discord", "Discord"],
];

const STATUS: Record<Recap["status"], { label: string; tone: string }> = {
  draft: { label: "Waiting for you", tone: "is-open" },
  approved: { label: "Approved, posting shortly", tone: "is-ok" },
  posting: { label: "Posting now", tone: "is-ok" },
  posted: { label: "Posted", tone: "is-ok" },
  skipped: { label: "Skipped", tone: "is-miss" },
  failed: { label: "Some channels failed", tone: "is-miss" },
};

const GROUPS: Record<string, string> = {
  "every card": "On every card",
  "card 1": "Card 1 · the week",
  "card 2": "Card 2 · three we got right",
  "card 3": "Card 3 · the one that got away",
  card: "The card",
  posts: "Post text",
};

/** Close to how X counts: most emoji and symbols weigh 2, URLs 23. */
function tweetWeight(text: string): number {
  let total = 0;
  for (const part of text.split(/(https?:\/\/\S+)/)) {
    if (/^https?:\/\//.test(part)) {
      total += 23;
      continue;
    }
    for (const ch of part) {
      const cp = ch.codePointAt(0) ?? 0;
      const light = cp <= 4351 || (cp >= 8192 && cp <= 8205) || (cp >= 8208 && cp <= 8223) || (cp >= 8242 && cp <= 8247);
      total += light ? 1 : 2;
    }
  }
  return total;
}

function finalCaption(texts: Texts): string {
  const caption = (texts.caption ?? "").trim();
  const lesson = (texts.lesson ?? "").trim();
  if (!lesson || caption.includes(lesson)) return caption;
  const cut = caption.lastIndexOf("\n\n");
  if (cut < 0) return `${caption}\n\n${lesson}`;
  return `${caption.slice(0, cut)}\n\n${lesson}${caption.slice(cut)}`;
}

function fmtPeriod(iso: string, kind: Kind): string {
  const first = new Date(`${iso}T00:00:00Z`);
  const opts: Intl.DateTimeFormatOptions = { day: "numeric", month: "short", timeZone: "UTC" };
  if (kind === "day") return first.toLocaleDateString(undefined, { ...opts, weekday: "long" });
  const last = new Date(first.getTime() + 6 * 86400000);
  return `${first.toLocaleDateString(undefined, opts)} – ${last.toLocaleDateString(undefined, opts)}`;
}

function fmtWhen(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function AdminRecap({ api }: { api: Api }) {
  const [kind, setKind] = useState<Kind>("week");
  const [payload, setPayload] = useState<Payload | null>(null);
  const [texts, setTexts] = useState<Texts | null>(null);
  const [channels, setChannels] = useState<Channels>({});
  const [week, setWeek] = useState<string | null>(null);
  const [pickDay, setPickDay] = useState("");
  const [only, setOnly] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [previews, setPreviews] = useState<string[]>([]);
  const previewTimer = useRef<number | undefined>(undefined);
  const recap = payload?.recap ?? null;

  const adopt = useCallback((next: Payload) => {
    setPayload((prev) => ({ ...prev, ...next, weeks: next.weeks ?? prev?.weeks }));
    setTexts(next.recap ? { ...next.recap.texts } : null);
    setChannels(next.recap?.channels ?? {});
  }, []);

  const load = useCallback(async () => {
    setError("");
    try {
      adopt(await api<Payload>(`/api/admin/recap?kind=${kind}${week ? `&week=${week}` : ""}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "load failed");
    }
  }, [api, kind, week, adopt]);

  useEffect(() => {
    void load();
  }, [load]);

  const savedFilter = recap?.kind === "day" ? (recap.data?.strategy_filter ?? []).join(",") : "";
  useEffect(() => {
    setOnly(savedFilter ? savedFilter.split(",") : []);
  }, [savedFilter, recap?.week_start]);

  const dirty = useMemo(() => {
    if (!recap || !texts) return false;
    return JSON.stringify(texts) !== JSON.stringify(recap.texts) || JSON.stringify(channels) !== JSON.stringify(recap.channels);
  }, [recap, texts, channels]);

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  // Re-render the cards from the text as typed, a moment after typing stops.
  useEffect(() => {
    if (!recap || !texts) return;
    window.clearTimeout(previewTimer.current);
    let cancelled = false;
    const made: string[] = [];
    previewTimer.current = window.setTimeout(async () => {
      try {
        for (let card = 1; card <= recap.card_count; card++) {
          const res = await fetch(`/api/admin/recap/${recap.week_start}/preview/${card}?kind=${recap.kind}`, {
            method: "POST",
            credentials: "include",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ texts }),
          });
          if (!res.ok) throw new Error(`preview HTTP ${res.status}`);
          made.push(URL.createObjectURL(await res.blob()));
        }
        if (!cancelled) {
          setPreviews((old) => {
            old.forEach((url) => URL.revokeObjectURL(url));
            return made;
          });
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "preview failed");
      }
    }, 700);
    return () => {
      cancelled = true;
      window.clearTimeout(previewTimer.current);
    };
  }, [recap, texts]);

  async function save(): Promise<void> {
    if (!recap || !texts) return;
    adopt(
      await api<Payload>(`/api/admin/recap/${recap.week_start}?kind=${recap.kind}`, {
        method: "PUT",
        body: JSON.stringify({ texts, channels }),
      }),
    );
  }

  async function run(label: string, work: () => Promise<void>) {
    setBusy(true);
    setError("");
    setStatus("");
    try {
      await work();
      setStatus(label);
    } catch (err) {
      setError(err instanceof Error ? err.message : "failed");
    } finally {
      setBusy(false);
    }
  }

  const draft = (target?: string) =>
    run("Draft built from the signals.", async () => {
      const q = new URLSearchParams({ kind });
      if (target) q.set("week", target);
      if (kind === "day" && only.length) q.set("strategies", only.join(","));
      adopt(await api<Payload>(`/api/admin/recap/draft?${q}`, { method: "POST" }));
      setWeek(target ?? null);
    });

  const approve = () =>
    run("Approved. The bot posts it within a minute.", async () => {
      if (!recap) return;
      if (dirty) await save();
      adopt(await api<Payload>(`/api/admin/recap/${recap.week_start}/approve?kind=${recap.kind}`, { method: "POST" }));
    });

  const skip = () =>
    run("Skipped. Nothing will be posted for this one.", async () => {
      if (!recap) return;
      adopt(await api<Payload>(`/api/admin/recap/${recap.week_start}/skip?kind=${recap.kind}`, { method: "POST" }));
    });

  const switchKind = (next: Kind) => {
    if (next === kind) return;
    if (dirty && !window.confirm("Leave without saving your edits?")) return;
    setKind(next);
    setWeek(null);
    setPayload(null);
    setPreviews([]);
  };

  const tabs = (
    <div className="rc-tabs">
      <button type="button" className={kind === "week" ? "is-on" : ""} onClick={() => switchKind("week")}>
        Weekly
      </button>
      <button type="button" className={kind === "day" ? "is-on" : ""} onClick={() => switchKind("day")}>
        Daily
      </button>
    </div>
  );

  const choices = payload?.strategies ?? [];
  const toggle = (key: string) =>
    setOnly((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]));
  const strategyPicker =
    kind === "day" && choices.length ? (
      <div className="rc-strategies" role="group" aria-label="Strategies in this recap">
        <span className="kit-muted">Strategies</span>
        <label className={only.length === 0 ? "is-on" : ""}>
          <input type="checkbox" checked={only.length === 0} disabled={busy} onChange={() => setOnly([])} />
          All
        </label>
        {choices.map((c) => (
          <label key={c.key} className={only.includes(c.key) ? "is-on" : ""} title={c.name}>
            <input type="checkbox" checked={only.includes(c.key)} disabled={busy} onChange={() => toggle(c.key)} />
            {c.name}
          </label>
        ))}
      </div>
    ) : null;
  const filterLabel = (keys: string[]) =>
    keys.map((k) => choices.find((c) => c.key === k)?.name ?? k).join(", ");

  const dayPicker =
    kind === "day" && payload ? (
      <div className="rc-draft-day">
        {strategyPicker}
        <button type="button" className="kit-btn" disabled={busy} onClick={() => void draft(payload.yesterday)}>
          Draft yesterday
        </button>
        <button type="button" className="kit-btn" disabled={busy} onClick={() => void draft(payload.today)}>
          Today so far
        </button>
        <input type="date" value={pickDay} max={payload.today} onChange={(e) => setPickDay(e.target.value)} />
        <button type="button" className="kit-btn" disabled={busy || !pickDay} onClick={() => void draft(pickDay)}>
          Draft that day
        </button>
      </div>
    ) : null;

  if (!payload) return <div className="rc">{tabs}<p className="kit-empty">{error || "Loading…"}</p></div>;

  if (!recap || !texts) {
    return (
      <div className="rc">
        {tabs}
        <div className="rc-empty kit-card">
          {kind === "week" ? (
            <>
              <h2>No weekly recap yet</h2>
              <p>
                The bot drafts last week's recap every Monday at 08:00 UTC and messages you on Telegram. You can build it
                now instead to see how it looks.
              </p>
              <div className="rc-actions">
                <button type="button" className="kit-btn is-primary" disabled={busy} onClick={() => void draft(payload.last_week)}>
                  Draft last week ({payload.last_week ? fmtPeriod(payload.last_week, "week") : "…"})
                </button>
                {payload.this_week ? (
                  <button type="button" className="kit-btn" disabled={busy} onClick={() => void draft(payload.this_week)}>
                    This week so far
                  </button>
                ) : null}
              </div>
            </>
          ) : (
            <>
              <h2>No daily recap yet</h2>
              <p>Daily recaps are never drafted for you. On a day that went well, draft it here, edit every word, and approve.</p>
              {dayPicker}
            </>
          )}
          {error ? <p className="kit-error">{error}</p> : null}
        </div>
      </div>
    );
  }

  const xWeight = tweetWeight(texts.x ?? "");
  const caption = finalCaption(texts);
  const lessonMissing = recap.needs_lesson && !(texts.lesson ?? "").trim();
  const st = STATUS[recap.status];
  const editable = recap.editable;
  const chosen = CHANNELS.some(([key]) => channels[key]);
  const blockers = [
    lessonMissing && "write what we learned",
    xWeight > 280 && "shorten the X post",
    caption.length > 1024 && "shorten the caption",
    !chosen && "pick a channel",
  ].filter(Boolean) as string[];

  const groups: [string, FieldSpec[]][] = [];
  for (const field of recap.fields) {
    const last = groups[groups.length - 1];
    if (last && last[0] === field.where) last[1].push(field);
    else groups.push([field.where, [field]]);
  }

  const hintFor = (field: FieldSpec): string => {
    if (field.key === "x") return `${xWeight} / 280`;
    if (field.key === "caption") return `${caption.length} / 1024${recap.needs_lesson ? " · the lesson is added above the last line" : ""}`;
    if (field.key === "lesson") return "yours to write · required";
    return field.hint;
  };
  const isNeed = (field: FieldSpec) =>
    editable && ((field.key === "lesson" && lessonMissing) || (field.key === "x" && xWeight > 280) || (field.key === "caption" && caption.length > 1024));

  return (
    <div className="rc">
      {tabs}
      <div className="rc-bar kit-card">
        <span className={`kit-pill ${st.tone}`}>
          <i>●</i>
          {st.label}
        </span>
        <b>{fmtPeriod(recap.week_start, recap.kind)}</b>
        <span className="kit-muted">{recap.headline}</span>
        {recap.kind === "day" && recap.data?.strategy_filter?.length ? (
          <span className="kit-pill is-open">Only: {filterLabel(recap.data.strategy_filter)}</span>
        ) : null}
        <div className="kit-card-right">
          {recap.status === "draft" && recap.deadline ? <span className="kit-muted">Approve by {fmtWhen(recap.deadline)}</span> : null}
          {recap.posted_at ? <span className="kit-muted">Posted {fmtWhen(recap.posted_at)}</span> : null}
          {payload.weeks && payload.weeks.length > 1 ? (
            <select value={recap.week_start} onChange={(e) => setWeek(e.target.value)}>
              {payload.weeks.map((w) => (
                <option key={w.week_start} value={w.week_start}>
                  {fmtPeriod(w.week_start, recap.kind)} · {w.status}
                </option>
              ))}
            </select>
          ) : null}
          {recap.status === "draft" ? (
            <button
              type="button"
              className="kit-btn"
              disabled={busy}
              title="Re-read the signals and start the text over. Your edits are lost."
              onClick={() => {
                if (!dirty || window.confirm("Rebuild the draft? Your edits will be lost.")) void draft(recap.week_start);
              }}
            >
              Rebuild draft
            </button>
          ) : null}
        </div>
      </div>
      {dayPicker}

      {Object.keys(recap.post_log || {}).length ? (
        <div className="rc-log">
          {CHANNELS.filter(([key]) => recap.post_log[key]).map(([key, label]) => {
            const entry = recap.post_log[key] as { ok: boolean; error?: string };
            return (
              <span key={key} className={`kit-pill ${entry.ok ? "is-ok" : "is-miss"}`} title={entry.error}>
                <i>{entry.ok ? "✓" : "✗"}</i>
                {label}
              </span>
            );
          })}
          {recap.status === "failed" ? <span className="kit-muted">Approve again to retry only the channels that failed.</span> : null}
        </div>
      ) : null}

      <div className="rc-grid">
        <div className="rc-previews">
          <div className="rc-cap">Preview · updates as you type</div>
          {Array.from({ length: recap.card_count }, (_, i) =>
            previews[i] ? (
              <a key={i} href={previews[i]} target="_blank" rel="noreferrer">
                <img src={previews[i]} alt={`Card ${i + 1}`} />
              </a>
            ) : (
              <div key={i} className="rc-ph" />
            ),
          )}
        </div>

        <div className="rc-form">
          {groups.map(([where, fields]) => (
            <section key={where} className="rc-group">
              <h3>{GROUPS[where] ?? where}</h3>
              {where === "card 3" && recap.notes.length ? (
                <div className="kit-note">
                  <h3>Worth knowing before you write the lesson</h3>
                  <ul>
                    {recap.notes.map((note) => (
                      <li key={note}>{note}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {fields.map((field) => (
                <Field key={field.key} label={field.label} hint={hintFor(field)} need={isNeed(field)}>
                  {field.rows > 1 ? (
                    <textarea
                      rows={field.rows}
                      value={texts[field.key] ?? ""}
                      disabled={!editable}
                      placeholder={field.key === "lesson" ? "One honest sentence about what this week taught you." : undefined}
                      onChange={(e) => setTexts((t) => (t ? { ...t, [field.key]: e.target.value } : t))}
                    />
                  ) : (
                    <input
                      value={texts[field.key] ?? ""}
                      disabled={!editable}
                      onChange={(e) => setTexts((t) => (t ? { ...t, [field.key]: e.target.value } : t))}
                    />
                  )}
                </Field>
              ))}
            </section>
          ))}

          <div className="rc-channels">
            {CHANNELS.map(([key, label]) => (
              <label key={key}>
                <input
                  type="checkbox"
                  checked={Boolean(channels[key])}
                  disabled={!editable}
                  onChange={(e) => setChannels((c) => ({ ...c, [key]: e.target.checked }))}
                />
                {label}
              </label>
            ))}
          </div>

          {editable ? (
            <div className="rc-actions">
              <button
                type="button"
                className="kit-btn is-primary"
                disabled={busy || blockers.length > 0}
                title={blockers.length ? `First: ${blockers.join(", ")}` : undefined}
                onClick={() => void approve()}
              >
                {recap.status === "failed" ? "Approve and retry" : "Approve and post"}
              </button>
              <button type="button" className="kit-btn" disabled={busy || !dirty} onClick={() => void run("Saved.", save)}>
                Save draft
              </button>
              {recap.status === "draft" ? (
                <button
                  type="button"
                  className="kit-btn"
                  disabled={busy}
                  onClick={() => {
                    if (window.confirm("Skip this one? Nothing will be posted.")) void skip();
                  }}
                >
                  Skip
                </button>
              ) : null}
              {blockers.length ? <span className="kit-muted">First: {blockers.join(", ")}.</span> : null}
            </div>
          ) : null}
          {status ? <p className="rc-status">{status}</p> : null}
          {error ? <p className="kit-error">{error}</p> : null}
        </div>
      </div>
    </div>
  );
}

function Field({ label, hint, need, children }: { label: string; hint?: string; need?: boolean; children: ReactNode }) {
  return (
    <label className={`rc-field ${need ? "is-need" : ""}`}>
      <span>
        {label}
        {hint ? <i>{hint}</i> : null}
      </span>
      {children}
    </label>
  );
}
