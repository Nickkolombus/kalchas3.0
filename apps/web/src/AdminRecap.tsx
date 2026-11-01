import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

type Api = <T>(path: string, init?: RequestInit) => Promise<T>;

type Pick = {
  match_id: string;
  home: string;
  away: string;
  league: string;
  minute: number;
  goal_minute: number | null;
  gap: number | null;
  team_name: string | null;
  why: string;
};

type Texts = {
  cover_line: string;
  calls: string[];
  honourable: string;
  miss: string;
  lesson: string;
  x: string;
  caption: string;
};

type Channels = Record<string, boolean>;

type Recap = {
  week_start: string;
  status: "draft" | "approved" | "posting" | "posted" | "skipped" | "failed";
  editable: boolean;
  deadline: string;
  headline: string;
  data: {
    total: number;
    goals: number;
    misses: number;
    calls: Pick[];
    honourable: Pick | null;
    miss: (Pick & { strategies: string[] }) | null;
  };
  texts: Texts;
  channels: Channels;
  post_log: Record<string, { ok: boolean; error?: string; ref?: string } | string>;
  notes: string[];
  limits: Record<string, { used: number; max: number }>;
  notified_at: string | null;
  approved_at: string | null;
  posted_at: string | null;
};

type Payload = { recap: Recap | null; weeks?: { week_start: string; status: string }[]; last_week?: string };

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
  const caption = texts.caption.trim();
  const lesson = texts.lesson.trim();
  if (!lesson || caption.includes(lesson)) return caption;
  const cut = caption.lastIndexOf("\n\n");
  if (cut < 0) return `${caption}\n\n${lesson}`;
  return `${caption.slice(0, cut)}\n\n${lesson}${caption.slice(cut)}`;
}

function fmtWeek(iso: string): string {
  const first = new Date(`${iso}T00:00:00Z`);
  const last = new Date(first.getTime() + 6 * 86400000);
  const opts: Intl.DateTimeFormatOptions = { day: "numeric", month: "short", timeZone: "UTC" };
  return `${first.toLocaleDateString(undefined, opts)} – ${last.toLocaleDateString(undefined, opts)}`;
}

function fmtWhen(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function AdminRecap({ api }: { api: Api }) {
  const [payload, setPayload] = useState<Payload | null>(null);
  const [texts, setTexts] = useState<Texts | null>(null);
  const [channels, setChannels] = useState<Channels>({});
  const [week, setWeek] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [previews, setPreviews] = useState<string[]>([]);
  const previewTimer = useRef<number | undefined>(undefined);
  const recap = payload?.recap ?? null;

  const adopt = useCallback((next: Payload) => {
    setPayload((prev) => ({ ...prev, ...next, weeks: next.weeks ?? prev?.weeks, last_week: next.last_week ?? prev?.last_week }));
    setTexts(next.recap ? { ...next.recap.texts, calls: [...(next.recap.texts.calls || [])] } : null);
    setChannels(next.recap?.channels ?? {});
  }, []);

  const load = useCallback(async () => {
    setError("");
    try {
      adopt(await api<Payload>(`/api/admin/recap${week ? `?week=${week}` : ""}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "load failed");
    }
  }, [api, week, adopt]);

  useEffect(() => {
    void load();
  }, [load]);

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

  const cardCount = recap ? 1 + (recap.data.calls.length ? 1 : 0) + (recap.data.miss ? 1 : 0) : 0;

  // Re-render the cards from the text as typed, a moment after typing stops.
  useEffect(() => {
    if (!recap || !texts) return;
    window.clearTimeout(previewTimer.current);
    let cancelled = false;
    const made: string[] = [];
    previewTimer.current = window.setTimeout(async () => {
      try {
        for (let card = 1; card <= cardCount; card++) {
          const res = await fetch(`/api/admin/recap/${recap.week_start}/preview/${card}`, {
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
  }, [recap, texts, cardCount]);

  async function save(): Promise<boolean> {
    if (!recap || !texts) return false;
    const next = await api<Payload>(`/api/admin/recap/${recap.week_start}`, {
      method: "PUT",
      body: JSON.stringify({ texts, channels }),
    });
    adopt(next);
    return true;
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

  const draftNow = (target?: string) =>
    run("Draft built from the week's signals.", async () => {
      const target_week = target ?? payload?.last_week;
      adopt(await api<Payload>(`/api/admin/recap/draft${target_week ? `?week=${target_week}` : ""}`, { method: "POST" }));
      setWeek(target_week ?? null);
    });

  const approve = () =>
    run("Approved. The bot posts it within a minute.", async () => {
      if (!recap) return;
      if (dirty) await save();
      adopt(await api<Payload>(`/api/admin/recap/${recap.week_start}/approve`, { method: "POST" }));
    });

  const skip = () =>
    run("Skipped. Nothing will be posted for this week.", async () => {
      if (!recap) return;
      adopt(await api<Payload>(`/api/admin/recap/${recap.week_start}/skip`, { method: "POST" }));
    });

  const setText = <K extends keyof Texts>(key: K, value: Texts[K]) => setTexts((t) => (t ? { ...t, [key]: value } : t));
  const setCall = (index: number, value: string) =>
    setTexts((t) => (t ? { ...t, calls: t.calls.map((c, i) => (i === index ? value : c)) } : t));

  if (!payload) return <p className="kit-empty">{error || "Loading…"}</p>;

  if (!recap || !texts) {
    return (
      <div className="rc-empty kit-card">
        <h2>No recap yet</h2>
        <p>
          The bot drafts last week's recap every Monday at 08:00 UTC and messages you on Telegram. You can build it now
          instead to see how it looks.
        </p>
        <button type="button" className="kit-btn is-primary" disabled={busy} onClick={() => void draftNow()}>
          Draft last week now
        </button>
        {error ? <p className="kit-error">{error}</p> : null}
      </div>
    );
  }

  const xWeight = tweetWeight(texts.x);
  const caption = finalCaption(texts);
  const lessonMissing = !texts.lesson.trim();
  const st = STATUS[recap.status];
  const editable = recap.editable;
  const chosen = CHANNELS.some(([key]) => channels[key]);
  const blockers = [
    lessonMissing && "write what we learned",
    xWeight > 280 && "shorten the X post",
    caption.length > 1024 && "shorten the caption",
    !chosen && "pick a channel",
  ].filter(Boolean) as string[];

  return (
    <div className="rc">
      <div className="rc-bar kit-card">
        <span className={`kit-pill ${st.tone}`}>
          <i>●</i>
          {st.label}
        </span>
        <b>{fmtWeek(recap.week_start)}</b>
        <span className="kit-muted">{recap.headline}</span>
        <div className="kit-card-right">
          {recap.status === "draft" ? <span className="kit-muted">Approve by {fmtWhen(recap.deadline)}</span> : null}
          {recap.posted_at ? <span className="kit-muted">Posted {fmtWhen(recap.posted_at)}</span> : null}
          {payload.weeks && payload.weeks.length > 1 ? (
            <select value={recap.week_start} onChange={(e) => setWeek(e.target.value)}>
              {payload.weeks.map((w) => (
                <option key={w.week_start} value={w.week_start}>
                  {fmtWeek(w.week_start)} · {w.status}
                </option>
              ))}
            </select>
          ) : null}
          {recap.status === "draft" ? (
            <button
              type="button"
              className="kit-btn"
              disabled={busy}
              title="Re-read the week's signals and start the text over. Your edits are lost."
              onClick={() => {
                if (!dirty || window.confirm("Rebuild the draft? Your edits will be lost.")) void draftNow(recap.week_start);
              }}
            >
              Rebuild draft
            </button>
          ) : null}
        </div>
      </div>

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
          {Array.from({ length: cardCount }, (_, i) =>
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
          <Field label="Cover line" hint="under the headline on card 1">
            <textarea rows={2} value={texts.cover_line} disabled={!editable} onChange={(e) => setText("cover_line", e.target.value)} />
          </Field>

          {recap.data.calls.map((call, i) => (
            <Field key={call.match_id} label={`Call ${i + 1} · ${call.home} v ${call.away}`} hint={`picked: ${call.why}`}>
              <textarea rows={3} value={texts.calls[i] ?? ""} disabled={!editable} onChange={(e) => setCall(i, e.target.value)} />
            </Field>
          ))}

          {recap.data.calls.length ? (
            <Field label="Footer of card 2" hint="honourable mention, or leave empty">
              <input value={texts.honourable} disabled={!editable} onChange={(e) => setText("honourable", e.target.value)} />
            </Field>
          ) : null}

          {recap.data.miss ? (
            <Field label={`The miss · ${recap.data.miss.home} v ${recap.data.miss.away}`} hint={`picked: ${recap.data.miss.why}`}>
              <textarea rows={3} value={texts.miss} disabled={!editable} onChange={(e) => setText("miss", e.target.value)} />
            </Field>
          ) : null}

          {recap.notes.length ? (
            <div className="kit-note">
              <h3>Worth knowing before you write the lesson</h3>
              <ul>
                {recap.notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </div>
          ) : null}

          <Field label="What we learned" hint="yours to write · required" need={lessonMissing && editable}>
            <textarea
              rows={2}
              value={texts.lesson}
              disabled={!editable}
              placeholder="One honest sentence about what this week taught you."
              onChange={(e) => setText("lesson", e.target.value)}
            />
          </Field>

          <Field label="X post" hint={`${xWeight} / 280`} need={xWeight > 280}>
            <textarea rows={4} value={texts.x} disabled={!editable} onChange={(e) => setText("x", e.target.value)} />
          </Field>

          <Field
            label="Telegram and Discord caption"
            hint={`${caption.length} / 1024 · the lesson is added above the last line`}
            need={caption.length > 1024}
          >
            <textarea rows={7} value={texts.caption} disabled={!editable} onChange={(e) => setText("caption", e.target.value)} />
          </Field>

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
              <button type="button" className="kit-btn" disabled={busy || !dirty} onClick={() => void run("Saved.", async () => void (await save()))}>
                Save draft
              </button>
              {recap.status === "draft" ? (
                <button
                  type="button"
                  className="kit-btn"
                  disabled={busy}
                  onClick={() => {
                    if (window.confirm("Skip this week? Nothing will be posted.")) void skip();
                  }}
                >
                  Skip this week
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
