import { useCallback, useEffect, useState } from "react";

/* Posted parlay slips, newest first: where each went, how the legs went, and
   anything waiting on the admin (a called-off leg, a result to post). The bot
   does the posting, settling and replying; this page follows it. */

type Api = <T>(path: string, init?: RequestInit) => Promise<T>;

type Entry = { ok: boolean; ref?: string; to?: string; error?: string; at?: string; retry?: boolean };

type SlipLeg = {
  match_id: string;
  kickoff: string;
  label: string;
  price: number;
  home: { name: string };
  away: { name: string };
};

type LegOutcome = {
  outcome?: "landed" | "missed" | "void";
  state?: "off" | "unjudged";
  note?: string;
  score?: string;
  by?: string;
};

type Slip = {
  id: number;
  day: string;
  slot: "today" | "tomorrow" | "nightly";
  style: string;
  legs: SlipLeg[];
  channels: Record<string, boolean>;
  autopost: boolean;
  status: string;
  post_log: Record<string, Entry>;
  outcomes: Record<string, LegOutcome>;
  reply_log: Record<string, Entry>;
  result: string | null;
  created_at: string;
  updated_at: string;
  verdict: {
    done: boolean;
    result: "came_in" | "lost" | "void" | null;
    landed: number;
    missed: number;
    void: number;
    legs: number;
    combined: number;
    returns: number;
  };
};

export const CHANNELS: { key: string; label: string }[] = [
  { key: "x", label: "X" },
  { key: "telegram_free", label: "Telegram free" },
  { key: "telegram_paid", label: "Telegram paid" },
  { key: "discord_free", label: "Discord free" },
  { key: "discord_paid", label: "Discord paid" },
];

// A failed channel can be sent again until the slip settles (the API holds the same list).
const RETRYABLE = new Set(["failed", "posted", "needs_decision", "approved"]);

const SLOT: Record<string, string> = { today: "Today", tomorrow: "Tomorrow", nightly: "Nightly" };

const CHOICES: Record<string, { value: "void" | "missed" | "landed"; label: string }[]> = {
  off: [
    { value: "void", label: "Void: drop it" },
    { value: "missed", label: "Count as lost" },
  ],
  unjudged: [
    { value: "landed", label: "It landed" },
    { value: "missed", label: "It missed" },
  ],
};

function statusLine(s: Slip): { text: string; tone: "wait" | "ok" | "bad" | "ask" } {
  const decided = Object.values(s.outcomes).filter((o) => o.outcome).length;
  switch (s.status) {
    case "approved":
      return { text: "Queued: the bot posts it within a minute", tone: "wait" };
    case "posting":
      return { text: "Posting…", tone: "wait" };
    case "failed":
      return { text: "Every channel failed", tone: "bad" };
    case "posted":
      return { text: `Posted · ${decided} of ${s.legs.length} legs decided`, tone: "wait" };
    case "needs_decision":
      return { text: "Needs your call on a leg", tone: "ask" };
    case "awaiting_reply":
      return { text: "Settled · the result waits for you", tone: "ask" };
    case "reply_approved":
    case "replying":
      return { text: "Posting the result…", tone: "wait" };
    case "replied":
      return { text: "Result posted", tone: "ok" };
    case "reply_failed":
      return { text: "The result reply failed somewhere", tone: "bad" };
    case "reply_skipped":
      return { text: "Result not posted (skipped)", tone: "wait" };
    default:
      return { text: s.status, tone: "wait" };
  }
}

function resultText(s: Slip): string | null {
  const v = s.verdict;
  if (!v.done) return null;
  if (v.result === "came_in") return `Came in · odds ${v.combined.toFixed(2)} · 10 returned ${v.returns.toFixed(2)}`;
  if (v.result === "lost") return `Lost · ${v.landed} of ${v.legs} landed`;
  return "Void · every leg called off";
}

function when(iso: string): string {
  const at = new Date(iso);
  return Number.isNaN(at.getTime()) ? "" : at.toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function AdminParlayPosted({ api, refresh }: { api: Api; refresh: number }) {
  const [slips, setSlips] = useState<Slip[] | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const body = await api<{ slips: Slip[] }>("/api/admin/parlay/slips?limit=40");
      setSlips(body.slips);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load the slips");
    }
  }, [api]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, 20_000);
    return () => window.clearInterval(timer);
  }, [load, refresh]);

  useEffect(() => {
    if (slips && slips.length && open === null && refresh) setOpen(slips[0].id);
  }, [slips, open, refresh]);

  const act = async (path: string, body?: unknown) => {
    try {
      await api(path, { method: "POST", body: JSON.stringify(body ?? {}) });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "That didn't work");
    }
  };

  const retryChannel = (s: Slip, channel: string, label: string) => {
    const started = s.legs.filter((l) => new Date(l.kickoff).getTime() <= Date.now()).length;
    if (started && !window.confirm(`${started} of ${s.legs.length} matches have already kicked off. Post slip #${s.id} to ${label} anyway?`)) return;
    void act(`/api/admin/parlay/slips/${s.id}/retry/${channel}`);
  };

  if (error && !slips) return <p className="kit-error">{error}</p>;
  if (!slips) return <p className="kit-empty">Loading…</p>;
  if (!slips.length)
    return (
      <div className="kit-card kit-card-body">
        <p className="kit-empty">Nothing posted yet. Slips you post from Build a slip show up here with their results.</p>
      </div>
    );

  return (
    <div className="ap-posted">
      {error ? <p className="kit-error">{error}</p> : null}
      {slips.map((s) => {
        const st = statusLine(s);
        const res = resultText(s);
        const isOpen = open === s.id;
        const asks = s.legs.filter((l) => s.outcomes[l.match_id]?.state && !s.outcomes[l.match_id]?.outcome);
        return (
          <div key={s.id} className={`kit-card ap-slipcard is-${st.tone}`}>
            <button type="button" className="ap-slipcard-head" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : s.id)}>
              <span className="ap-slipcard-title">
                <b>#{s.id}</b> {SLOT[s.slot] ?? s.slot} · {s.legs.length} legs · {s.style}
                <small> · {when(s.created_at)}</small>
              </span>
              <span className={`ap-pill is-${st.tone}`}>{st.text}</span>
              {res ? <span className={`ap-result is-${s.verdict.result}`}>{res}</span> : null}
            </button>

            {isOpen ? (
              <div className="ap-slipcard-body">
                <div className="ap-slip">
                  <img src={`/api/admin/parlay/slips/${s.id}/image?v=${encodeURIComponent(s.updated_at)}`} alt={`Slip #${s.id}`} loading="lazy" />
                </div>
                <div className="ap-slipcard-side">
                  <h3>Channels</h3>
                  <ul className="ap-chanlog">
                    {CHANNELS.filter((c) => s.channels[c.key]).map((c) => {
                      const p = s.post_log[c.key];
                      const r = s.reply_log[c.key];
                      return (
                        <li key={c.key}>
                          <span>{c.label}</span>
                          {p?.retry ? (
                            <span className="kit-muted">sending again…</span>
                          ) : p && !p.ok && RETRYABLE.has(s.status) ? (
                            <span className="ap-chanfail">
                              <span className="is-bad" title={p.error ?? ""}>failed: {p.error ?? ""}</span>
                              <button type="button" className="kit-btn ap-chanretry" onClick={() => retryChannel(s, c.key, c.label)}>
                                Retry
                              </button>
                            </span>
                          ) : (
                            <span className={p ? (p.ok ? "is-ok" : "is-bad") : "kit-muted"} title={p?.error ?? ""}>
                              {p ? (p.ok ? "posted" : `failed: ${p.error ?? ""}`) : "waiting"}
                            </span>
                          )}
                          <span className={r ? (r.ok ? "is-ok" : "is-bad") : "kit-muted"} title={r?.error ?? ""}>
                            {r ? (r.ok ? "result replied" : `reply failed: ${r.error ?? ""}`) : p?.ok ? "result to come" : ""}
                          </span>
                        </li>
                      );
                    })}
                  </ul>

                  <h3>Legs</h3>
                  <ol className="ap-leglog">
                    {s.legs.map((l) => {
                      const o = s.outcomes[l.match_id];
                      return (
                        <li key={l.match_id} className={o?.outcome ? `is-${o.outcome}` : o?.state ? "is-ask" : ""}>
                          <span>
                            {l.home.name} v {l.away.name} · {l.label} {l.price.toFixed(2)}
                          </span>
                          <small>
                            {o?.outcome
                              ? `${o.outcome === "void" ? "Void" : o.outcome === "landed" ? "Landed" : "Missed"}${o.score ? ` · ${o.score}` : ""}${o.note ? ` · ${o.note}` : ""}${o.by === "admin" ? " · your call" : ""}`
                              : o?.state
                                ? `${o.note ?? ""} · waiting for your call`
                                : "Not played yet"}
                          </small>
                        </li>
                      );
                    })}
                  </ol>

                  {asks.length ? (
                    <div className="ap-asks">
                      <h3>Your call</h3>
                      {asks.map((l) => {
                        const o = s.outcomes[l.match_id];
                        return (
                          <div key={l.match_id} className="ap-ask">
                            <p>
                              {l.home.name} v {l.away.name}:{" "}
                              {o.state === "off" ? `${(o.note ?? "called off").toLowerCase()}.` : `finished ${o.score ?? ""}, but the result can't settle ${l.label}.`}
                            </p>
                            {(CHOICES[o.state ?? ""] ?? []).map((c) => (
                              <button key={c.value} type="button" className="kit-btn" onClick={() => void act(`/api/admin/parlay/slips/${s.id}/decide`, { match_id: l.match_id, outcome: c.value })}>
                                {c.label}
                              </button>
                            ))}
                          </div>
                        );
                      })}
                      <p className="kit-sub">The same question is in your Telegram admin chat; answer either.</p>
                    </div>
                  ) : null}

                  <div className="ap-actions">
                    {s.status === "awaiting_reply" || s.status === "reply_skipped" ? (
                      <button type="button" className="kit-btn is-primary" onClick={() => void act(`/api/admin/parlay/slips/${s.id}/reply`, { action: "post" })}>
                        Post the result
                      </button>
                    ) : null}
                    {s.status === "awaiting_reply" ? (
                      <button type="button" className="kit-btn" onClick={() => void act(`/api/admin/parlay/slips/${s.id}/reply`, { action: "skip" })}>
                        Skip
                      </button>
                    ) : null}
                    {s.status === "reply_failed" ? (
                      <button type="button" className="kit-btn" onClick={() => void act(`/api/admin/parlay/slips/${s.id}/reply`, { action: "retry" })}>
                        Retry the failed replies
                      </button>
                    ) : null}
                    {s.status === "failed" ? (
                      <button type="button" className="kit-btn" onClick={() => void act(`/api/admin/parlay/slips/${s.id}/retry`)}>
                        Try posting again
                      </button>
                    ) : null}
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
