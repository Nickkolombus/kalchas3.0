import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import "./styles/alert-text.css";
import type { Api } from "./AdminKit";

type Channel = "paid" | "free" | "discord" | "x";
type Kind = "alert" | "goal" | "miss";
type Mode = "blocks" | "text";

type Slot = {
  saved: boolean;
  body: string;
  enabled: boolean;
  updated_at: string | null;
  fallback_count: number;
  last_fallback_at: string | null;
  last_fallback_reason: string | null;
  limit: number;
};

type Tag = {
  name: string;
  label: string;
  group: string;
  example: string;
  kinds: Kind[];
  block: boolean;
};

type Sample = { ids: number[]; label: string; lead: string };
type Strategy = { key: string; label: string; short: string };

type Payload = {
  strategies: Strategy[];
  channels: { key: Channel; kinds: Kind[] }[];
  templates: Record<string, Record<Channel, Partial<Record<Kind, Slot>>>>;
  defaults: Record<Channel, Partial<Record<Kind, string>>>;
  tags: Tag[];
  samples: Record<Kind, Sample[]>;
};

type Preview = {
  problems: string[];
  telegram: string;
  discord: string;
  x: string;
  x_dropped: string[];
  x_weight: number;
  length: number;
  limit: number;
  fell_back: string | null;
  discord_follows: boolean;
  x_follows: boolean;
  example: boolean;
  /** Each tag's value for the previewed alert (Telegram HTML). */
  values?: Record<string, string>;
};

const DEFAULT = "default";

const CHANNELS: { key: Channel; label: string; note: string }[] = [
  { key: "paid", label: "Telegram paid", note: "The paid channel. Discord's paid channel gets the same text unless Discord has its own." },
  { key: "free", label: "Telegram free", note: "The free channel. Discord's free channel and X get this text too, unless they have their own." },
  { key: "discord", label: "Discord", note: "Both Discord channels. Without its own text, Discord gets the matching Telegram text." },
  { key: "x", label: "X", note: "One tweet with the banner. Past 280 characters, lines are dropped from the bottom (lines with a link stay). Without its own text, X gets the free channel's text and the match link." },
];

const KINDS: { key: Kind; label: string; note: string }[] = [
  { key: "alert", label: "Alert", note: "Sent with the banner when a signal fires. When several strategies fire on the same minute, the one that ranks highest (Δ5′, Δ10′, Form Bar, UrG, K) picks the text and the stats; every strategy's line is listed." },
  { key: "goal", label: "Goal reply", note: "Sent as a reply under the alert when a goal comes. Each alert uses its own strategy's text." },
  { key: "miss", label: "No-goal reply", note: "X only: X has no reactions, so a miss is a reply. Telegram and Discord get a 😢 reaction instead." },
];

/** Which stretch of the match a stat block covers. "auto" follows the strategy that fired. */
type Span = "l5" | "l10" | "match" | "auto";

const SPANS: Record<Span, { short: string; group: string; note: string }> = {
  l5: { short: "Last 5", group: "Last 5 minutes", note: "Same numbers whichever strategy fired." },
  l10: { short: "Last 10", group: "Last 10 minutes", note: "Same numbers whichever strategy fired." },
  match: { short: "Match", group: "Whole match so far", note: "From kickoff to the signal." },
  auto: {
    short: "Follows strategy",
    group: "Follows the strategy",
    note: "What Default uses: last 5 mins on Δ5′, last 10 on Δ10′, whole match on every other strategy (no heading).",
  },
};

/** One line of a template, and the block it shows as. ``hidden`` ones only label old saved lines. */
type Piece = { key: string; label: string; group: string; line: string; kinds: Kind[]; span?: Span; hidden?: boolean };

const ALL: Kind[] = ["alert", "goal", "miss"];

const FIVE: [string, string][] = [
  ["sot", "SOT"],
  ["sofft", "SOFFT"],
  ["da", "DA"],
  ["corners", "Corners"],
  ["possession", "Possession"],
];

function spanPieces(span: "l5" | "l10" | "match"): Piece[] {
  const group = SPANS[span].group;
  const extra: [string, string][] = span === "match" ? [["attacks", "Attacks"], ["yellow", "Yellow cards"], ["red", "Red cards"]] : [];
  return [
    { key: `${span}_heading`, label: "Heading", group, line: `{${span}_heading}`, kinds: ALL, span },
    ...[...FIVE, ...extra].map(([stat, label]) => ({ key: `${span}_${stat}`, label, group, line: `{${span}_${stat}}`, kinds: ALL, span })),
    { key: `${span}_stats`, label: "Heading + all five", group, line: `{${span}_stats}`, kinds: ALL, span },
  ];
}

const AUTO = SPANS.auto.group;
const OLD_MATCH = "Whole match (old style)";

const PIECES: Piece[] = [
  { key: "versus", label: "Match line", group: "Match", line: "{versus}", kinds: ["alert"] },
  { key: "league", label: "League", group: "Match", line: "_{league}_", kinds: ALL },
  { key: "country", label: "Country", group: "Match", line: "{country}", kinds: ALL },
  { key: "score", label: "Score at the signal", group: "Match", line: "Score: {score}", kinds: ALL },
  { key: "tslg", label: "Minutes since each team scored", group: "Match", line: "Since last goal: {time_since_goal}", kinds: ALL },
  { key: "strategy_lines", label: "Strategy line(s) with reading", group: "Signal", line: "{strategy_lines}", kinds: ["alert"] },
  { key: "chance", label: "Scoring chance", group: "Signal", line: "Chance to score: {chance}", kinds: ALL },
  { key: "chance_odds", label: "Chance from odds alone", group: "Signal", line: "Odds alone: {chance_odds_only}", kinds: ALL },
  { key: "form_note", label: "Form Bar note", group: "Signal", line: "{form_note}", kinds: ["alert"] },
  ...spanPieces("l5"),
  ...spanPieces("l10"),
  ...spanPieces("match"),
  // Whole-match lines saved before the span groups existed: plain numbers, shown even at 0 - 0.
  { key: "m_sot", label: "SOT", group: OLD_MATCH, line: "SOT: {sot_home} - {sot_away}", kinds: ALL, span: "match", hidden: true },
  { key: "m_sofft", label: "SOFFT", group: OLD_MATCH, line: "SOFFT: {shots_off_home} - {shots_off_away}", kinds: ALL, span: "match", hidden: true },
  { key: "m_da", label: "DA", group: OLD_MATCH, line: "DA: {dangerous_attacks_home} - {dangerous_attacks_away}", kinds: ALL, span: "match", hidden: true },
  { key: "m_attacks", label: "Attacks", group: OLD_MATCH, line: "Attacks: {attacks_home} - {attacks_away}", kinds: ALL, span: "match", hidden: true },
  { key: "m_corners", label: "Corners", group: OLD_MATCH, line: "Corners: {corners_home} - {corners_away}", kinds: ALL, span: "match", hidden: true },
  { key: "m_possession", label: "Possession", group: OLD_MATCH, line: "Possession: {possession_home} - {possession_away}", kinds: ALL, span: "match", hidden: true },
  { key: "m_cards", label: "Yellow cards", group: OLD_MATCH, line: "Yellow cards: {yellow_home} - {yellow_away}", kinds: ALL, span: "match", hidden: true },
  { key: "m_red", label: "Red cards", group: OLD_MATCH, line: "Red cards: {red_home} - {red_away}", kinds: ALL, span: "match", hidden: true },
  { key: "stats_heading", label: "Heading (Δ5′ / Δ10′ only)", group: AUTO, line: "{stats_heading}", kinds: ["alert"], span: "auto" },
  ...FIVE.map(([stat, label]) => ({ key: `stat_${stat}`, label, group: AUTO, line: `{stat_${stat}}`, kinds: ["alert"] as Kind[], span: "auto" as Span })),
  { key: "stats", label: "Heading or Form Bar note + all five", group: AUTO, line: "{stats}", kinds: ["alert"], span: "auto" },
  { key: "odds", label: "Kickoff odds 1 / X / 2", group: "Odds and head to head", line: "Odds: {odds_home} / {odds_draw} / {odds_away}", kinds: ALL },
  { key: "favourite", label: "Favourite at kickoff", group: "Odds and head to head", line: "Favourite: {favourite}", kinds: ALL },
  { key: "team_odds", label: "Odds of the signal's team", group: "Odds and head to head", line: "{team} at kickoff: {team_odds}", kinds: ALL },
  { key: "h2h", label: "Head to head", group: "Odds and head to head", line: "H2H: {h2h_home_wins}-{h2h_draws}-{h2h_away_wins} in {h2h_meetings}", kinds: ALL },
  { key: "lede", label: "The alert's first lines", group: "Reply", line: "{lede}", kinds: ["goal", "miss"] },
  { key: "lede_tick", label: "✅ + the alert's first lines", group: "Reply", line: "✅ {lede}", kinds: ["goal"] },
  { key: "goal_line", label: "⚽ GOAL at minute · score", group: "Reply", line: "⚽ {goal_line}", kinds: ["goal"] },
  { key: "scorer", label: "Who scored", group: "Reply", line: "{scoring_team} scores!", kinds: ["goal"] },
  { key: "miss_line", label: "❌ No goal within the window", group: "Reply", line: "❌ {miss_line}", kinds: ["miss"] },
  { key: "miss_strategy", label: "Strategy and team", group: "Reply", line: "{miss_strategy}", kinds: ["miss"] },
  { key: "link", label: "Match link", group: "Link and your text", line: "↳ {match_link}", kinds: ALL },
];

const PIECE_BY_LINE = new Map(PIECES.map((p) => [p.line, p]));

/** What a one-line block says for the previewed alert, as plain text.
 *  "" when every tag in it is empty (the bot leaves that line out); null when unknown. */
function lineValue(line: string, values: Record<string, string> | undefined): string | null {
  if (!values) return null;
  const tags = [...line.matchAll(/\{([a-z0-9_]+)\}/g)].map((m) => m[1]);
  if (!tags.length) return null;
  if (tags.every((t) => !values[t])) return "";
  const filled = line.replace(/\{([a-z0-9_]+)\}/g, (_, t: string) => values[t] ?? "");
  return decode(filled.replace(/<[^>]+>/g, "")).replace(/\*\*/g, "").replace(/^_|_$/g, "");
}

function SpanLabel({ span }: { span: Span }) {
  return <span className={`at-span at-span-${span}`}>{SPANS[span].short}</span>;
}

function slotKey(strategy: string, channel: Channel, kind: Kind): string {
  return `${strategy}/${channel}/${kind}`;
}

function fmtWhen(iso: string | null): string {
  if (!iso) return "";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  return at.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function decode(text: string): string {
  return text
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, "&");
}

/** Telegram HTML as React: only <b> and <i> exist in what the bot sends. No innerHTML. */
function TelegramText({ html }: { html: string }) {
  const nodes: ReactNode[] = [];
  let bold = 0;
  let italic = 0;
  html.split(/(<\/?[bi]>)/).forEach((part, i) => {
    if (part === "<b>") bold += 1;
    else if (part === "</b>") bold = Math.max(0, bold - 1);
    else if (part === "<i>") italic += 1;
    else if (part === "</i>") italic = Math.max(0, italic - 1);
    else if (part) {
      let node: ReactNode = decode(part.replace(/<[^>]+>/g, ""));
      if (italic) node = <em>{node}</em>;
      if (bold) node = <strong>{node}</strong>;
      nodes.push(<Fragment key={i}>{node}</Fragment>);
    }
  });
  return <>{nodes}</>;
}

/** Discord markdown as React: **bold** and *italic* only, which is all the bot produces. */
function DiscordText({ text }: { text: string }) {
  const nodes: ReactNode[] = [];
  text.split(/(\*\*[^*]+\*\*|\*[^*\n]+\*)/).forEach((part, i) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      nodes.push(<strong key={i}>{part.slice(2, -2)}</strong>);
    } else if (part.startsWith("*") && part.endsWith("*") && part.length > 2) {
      nodes.push(<em key={i}>{part.slice(1, -1)}</em>);
    } else if (part) {
      nodes.push(<Fragment key={i}>{part}</Fragment>);
    }
  });
  return <>{nodes}</>;
}

function loadMode(): Mode {
  try {
    return window.localStorage.getItem("kalchas.alertText.mode") === "text" ? "text" : "blocks";
  } catch {
    return "blocks";
  }
}

function saveMode(mode: Mode) {
  try {
    window.localStorage.setItem("kalchas.alertText.mode", mode);
  } catch {
    /* per-viewer convenience only */
  }
}

function isOn(slot: Slot | undefined): boolean {
  return Boolean(slot?.saved && slot.enabled);
}

export function AdminAlertText({ api }: { api: Api }) {
  const [data, setData] = useState<Payload | null>(null);
  const [error, setError] = useState("");
  const [strategy, setStrategy] = useState<string>(DEFAULT);
  const [channel, setChannel] = useState<Channel>("paid");
  const [kind, setKind] = useState<Kind>("alert");
  const [mode, setMode] = useState<Mode>(loadMode);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [enabledDrafts, setEnabledDrafts] = useState<Record<string, boolean>>({});
  const [sampleIds, setSampleIds] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewError, setPreviewError] = useState("");
  const [saveProblems, setSaveProblems] = useState<string[]>([]);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [dragFrom, setDragFrom] = useState<number | null>(null);
  const area = useRef<HTMLTextAreaElement | null>(null);

  const load = useCallback(async () => {
    setError("");
    try {
      setData(await api<Payload>("/api/admin/alert-templates"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "load failed");
    }
  }, [api]);

  useEffect(() => {
    void load();
  }, [load]);

  const kinds: Kind[] = data?.channels.find((c) => c.key === channel)?.kinds ?? ["alert", "goal"];
  const activeKind: Kind = kinds.includes(kind) ? kind : "alert";
  const key = slotKey(strategy, channel, activeKind);
  const slot = data?.templates[strategy]?.[channel]?.[activeKind] ?? null;
  const defaultSlot = data?.templates[DEFAULT]?.[channel]?.[activeKind];
  const builtIn = data?.defaults[channel]?.[activeKind] ?? "";
  const body = drafts[key] ?? slot?.body ?? "";
  const enabled = enabledDrafts[key] ?? (slot ? (slot.saved ? slot.enabled : true) : true);
  const dirty = slot != null && (body !== slot.body || enabled !== (slot.saved ? slot.enabled : true) || !slot.saved);
  const isDefault = strategy === DEFAULT;
  const strategyInfo = data?.strategies.find((s) => s.key === strategy);

  // Samples where this strategy leads come first; any alert can be shown as this strategy.
  const samples = data?.samples[activeKind] ?? [];
  const own = isDefault ? samples : samples.filter((s) => s.lead === strategy);
  const others = isDefault ? [] : samples.filter((s) => s.lead !== strategy);
  const sampleKey = `${strategy}/${activeKind}`;
  const chosen = sampleIds[sampleKey] ?? (own[0] ?? others[0])?.ids.join("-") ?? "example";
  const sample = samples.find((s) => s.ids.join("-") === chosen) ?? null;

  useEffect(() => {
    setSaveProblems([]);
    setStatus("");
  }, [key]);

  useEffect(() => {
    if (!data) return;
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      try {
        const result = await api<Preview>("/api/admin/alert-templates/preview", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ strategy, channel, kind: activeKind, body, ids: sample?.ids ?? [] }),
        });
        if (!cancelled) {
          setPreview(result);
          setPreviewError("");
        }
      } catch (err) {
        if (!cancelled) setPreviewError(err instanceof Error ? err.message : "preview failed");
      }
    }, 300);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [api, data, strategy, channel, activeKind, body, sample]);

  const tagGroups = useMemo(() => {
    const groups: { name: string; tags: Tag[] }[] = [];
    for (const tag of data?.tags ?? []) {
      if (!tag.kinds.includes(activeKind)) continue;
      let group = groups.find((g) => g.name === tag.group);
      if (!group) {
        group = { name: tag.group, tags: [] };
        groups.push(group);
      }
      group.tags.push(tag);
    }
    const replyGroup = activeKind === "goal" ? "Goal reply" : activeKind === "miss" ? "No-goal reply" : "";
    if (replyGroup) groups.sort((a, b) => (a.name === replyGroup ? -1 : b.name === replyGroup ? 1 : 0));
    return groups;
  }, [data, activeKind]);

  const lines = useMemo(() => body.replace(/\r\n?/g, "\n").split("\n"), [body]);
  const used = useMemo(() => new Set(lines), [lines]);
  const pieceGroups = useMemo(() => {
    const groups: { name: string; pieces: Piece[] }[] = [];
    for (const piece of PIECES) {
      if (piece.hidden || !piece.kinds.includes(activeKind)) continue;
      let group = groups.find((g) => g.name === piece.group);
      if (!group) {
        group = { name: piece.group, pieces: [] };
        groups.push(group);
      }
      group.pieces.push(piece);
    }
    if (activeKind !== "alert") groups.sort((a, b) => (a.name === "Reply" ? -1 : b.name === "Reply" ? 1 : 0));
    return groups;
  }, [activeKind]);

  function setBody(next: string) {
    setDrafts((prev) => ({ ...prev, [key]: next }));
    setStatus("");
  }

  function setLines(next: string[]) {
    setBody(next.join("\n"));
  }

  function moveLine(from: number, to: number) {
    if (to < 0 || to >= lines.length || from === to) return;
    const next = [...lines];
    const [line] = next.splice(from, 1);
    next.splice(to, 0, line);
    setLines(next);
  }

  function addLine(line: string) {
    // Stats go after the last stat block already there; everything else goes at the end,
    // above a trailing link.
    const next = [...lines];
    let at = next.length;
    const linkAt = next.findIndex((l) => l.includes("{match_link}"));
    if (linkAt >= 0 && !line.includes("{match_link}")) {
      at = linkAt;
      while (at > 0 && next[at - 1].trim() === "") at -= 1;
    }
    next.splice(at, 0, line);
    setLines(next);
  }

  function insertTag(name: string) {
    const token = `{${name}}`;
    if (mode === "blocks") {
      addLine(token);
      return;
    }
    const el = area.current;
    if (!el) {
      setBody(body + token);
      return;
    }
    const start = el.selectionStart ?? body.length;
    const end = el.selectionEnd ?? body.length;
    setBody(body.slice(0, start) + token + body.slice(end));
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(start + token.length, start + token.length);
    });
  }

  function clearDrafts() {
    setDrafts((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
    setEnabledDrafts((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }

  async function save() {
    setBusy(true);
    setSaveProblems([]);
    setStatus("");
    try {
      const res = await fetch(`/api/admin/alert-templates/${strategy}/${channel}/${activeKind}`, {
        method: "PUT",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body, enabled }),
      });
      if (res.status === 422) {
        const out = (await res.json()) as { problems?: string[] };
        setSaveProblems(out.problems ?? ["Can't save this yet."]);
        return;
      }
      if (!res.ok) throw new Error(`save failed (${res.status})`);
      clearDrafts();
      await load();
      setStatus(enabled ? "Saved. The bot uses it from the next alert." : `Saved, switched off. ${isDefault ? "The built-in text" : "Default's text"} is used meanwhile.`);
    } catch (err) {
      setSaveProblems([err instanceof Error ? err.message : "save failed"]);
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    const back = isDefault ? "the built-in text" : "Default's text";
    if (!window.confirm(`Delete this text and go back to ${back}?`)) return;
    setBusy(true);
    try {
      if (slot?.saved) {
        await api(`/api/admin/alert-templates/${strategy}/${channel}/${activeKind}`, { method: "DELETE" });
      }
      clearDrafts();
      await load();
      setStatus(`Back to ${back}.`);
    } catch (err) {
      setSaveProblems([err instanceof Error ? err.message : "reset failed"]);
    } finally {
      setBusy(false);
    }
  }

  function chooseMode(next: Mode) {
    setMode(next);
    saveMode(next);
  }

  if (error) return <p className="kit-error">{error}</p>;
  if (!data || !slot) return <p className="kit-muted">Loading…</p>;

  const channelInfo = CHANNELS.find((c) => c.key === channel)!;
  const kindInfo = KINDS.find((k) => k.key === activeKind)!;
  const problems = saveProblems.length ? saveProblems : (preview?.problems ?? []);
  const isX = channel === "x";
  const over = preview != null && !isX && preview.length > preview.limit;
  const showTelegram = channel === "paid" || channel === "free";
  const showDiscord = activeKind !== "miss" && (channel === "discord" || preview?.discord_follows !== false) && !isX;
  const stratName = strategyInfo?.label ?? strategy;

  let pill: { on: boolean; text: string };
  if (isOn(slot)) pill = { on: true, text: isDefault ? "Default text in use" : `${stratName} has its own text here` };
  else if (!isDefault && isOn(defaultSlot)) pill = { on: false, text: slot.saved ? "Saved but switched off: Default's text in use" : "Uses Default's text" };
  else pill = { on: false, text: slot.saved ? "Saved but switched off: built-in text in use" : "Built-in text in use" };

  const strategyOn = (s: string) =>
    Object.values(data.templates[s] ?? {}).some((kindsMap) => Object.values(kindsMap).some((sl) => isOn(sl)));
  const channelOn = (c: Channel) => Object.values(data.templates[strategy]?.[c] ?? {}).some((sl) => isOn(sl));

  return (
    <div className="at">
      <article className="kit-card at-bar">
        <div className="at-row">
          <span className="at-row-label">Strategy</span>
          <div className="rc-tabs at-strats" role="tablist" aria-label="Strategy">
            {data.strategies.map((s) => (
              <button key={s.key} type="button" role="tab" aria-selected={s.key === strategy} className={s.key === strategy ? "is-on" : ""} onClick={() => setStrategy(s.key)}>
                {s.key === DEFAULT ? "Default" : <><b className="at-short">{s.short}</b> {s.label}</>}
                {strategyOn(s.key) ? <span className="at-dot" title="Has text of its own in use" /> : null}
              </button>
            ))}
          </div>
        </div>
        <div className="at-row">
          <span className="at-row-label">Where</span>
          <div className="rc-tabs" role="tablist" aria-label="Channel">
            {CHANNELS.map((c) => (
              <button key={c.key} type="button" role="tab" aria-selected={c.key === channel} className={c.key === channel ? "is-on" : ""} onClick={() => setChannel(c.key)}>
                {c.label}
                {channelOn(c.key) ? <span className="at-dot" title="Text in use" /> : null}
              </button>
            ))}
          </div>
          <div className="rc-tabs" role="tablist" aria-label="Message">
            {KINDS.filter((k) => kinds.includes(k.key)).map((k) => (
              <button key={k.key} type="button" role="tab" aria-selected={k.key === activeKind} className={k.key === activeKind ? "is-on" : ""} onClick={() => setKind(k.key)}>
                {k.label}
                {isOn(data.templates[strategy]?.[channel]?.[k.key]) ? <span className="at-dot" title="Text in use" /> : null}
              </button>
            ))}
          </div>
        </div>
        <p className="at-note">
          {isDefault
            ? "Default is used by every strategy that has no text of its own. "
            : `Only ${stratName} alerts (and joint posts it leads) use this. Until you save one, it uses Default's text. `}
          {channelInfo.note} {kindInfo.note}
        </p>
        <div className="at-state">
          <span className={`kit-pill ${pill.on ? "is-ok" : "is-open"}`}>
            <i>{pill.on ? "●" : "○"}</i>
            {pill.text}
          </span>
          {slot.updated_at ? <span className="kit-muted">Saved {fmtWhen(slot.updated_at)}</span> : null}
          {slot.fallback_count > 0 ? (
            <span className="at-warn">
              Fallback text went out instead {slot.fallback_count} {slot.fallback_count === 1 ? "time" : "times"} since saving
              {slot.last_fallback_at ? `, last ${fmtWhen(slot.last_fallback_at)}` : ""}
              {slot.last_fallback_reason ? `: ${slot.last_fallback_reason}` : ""}
            </span>
          ) : null}
        </div>
      </article>

      <div className="at-grid">
        <article className="kit-card at-edit">
          <div className="kit-card-head">
            <h2>{isDefault ? "Default text" : `${stratName} text`}</h2>
            <div className="kit-card-right">
              <div className="at-seg" role="tablist" aria-label="Edit as">
                <button type="button" role="tab" aria-selected={mode === "blocks"} className={mode === "blocks" ? "is-on" : ""} onClick={() => chooseMode("blocks")}>
                  Blocks
                </button>
                <button type="button" role="tab" aria-selected={mode === "text"} className={mode === "text" ? "is-on" : ""} onClick={() => chooseMode("text")}>
                  Text
                </button>
              </div>
            </div>
          </div>
          <div className="kit-card-body at-edit-body">
            {!isDefault && !slot.saved ? (
              <p className="at-inherit">
                Showing Default's text. Change anything and save to give {stratName} its own.
              </p>
            ) : null}
            {mode === "blocks" ? (
              <ol className={`at-blocks${problems.length ? " is-bad" : ""}`} aria-label="Message lines, top to bottom">
                {lines.map((line, i) => {
                  const piece = PIECE_BY_LINE.get(line);
                  const blank = line.trim() === "";
                  return (
                    <li
                      key={`${i}-${line}`}
                      className={`at-block-row${blank ? " is-blank" : ""}${dragFrom === i ? " is-drag" : ""}`}
                      draggable
                      onDragStart={(e) => {
                        setDragFrom(i);
                        e.dataTransfer.effectAllowed = "move";
                      }}
                      onDragOver={(e) => e.preventDefault()}
                      onDrop={(e) => {
                        e.preventDefault();
                        if (dragFrom !== null) moveLine(dragFrom, i);
                        setDragFrom(null);
                      }}
                      onDragEnd={() => setDragFrom(null)}
                    >
                      <span className="at-grip" aria-hidden="true">⋮⋮</span>
                      <div className="at-block-main">
                        <span className="at-block-name">
                          {blank ? (
                            "Blank line"
                          ) : piece ? (
                            <>
                              {piece.span ? <SpanLabel span={piece.span} /> : null}
                              {piece.label}
                            </>
                          ) : (
                            "Your line"
                          )}
                        </span>
                        {blank ? null : (
                          <input
                            className="at-block-line"
                            value={line}
                            spellCheck={false}
                            aria-label={`Line ${i + 1}`}
                            onChange={(e) => {
                              const next = [...lines];
                              next[i] = e.target.value;
                              setLines(next);
                            }}
                          />
                        )}
                      </div>
                      <div className="at-block-tools">
                        <button type="button" className="at-icon" title="Move up" aria-label="Move up" disabled={i === 0} onClick={() => moveLine(i, i - 1)}>↑</button>
                        <button type="button" className="at-icon" title="Move down" aria-label="Move down" disabled={i === lines.length - 1} onClick={() => moveLine(i, i + 1)}>↓</button>
                        <button type="button" className="at-icon" title="Remove" aria-label="Remove" onClick={() => setLines(lines.filter((_, j) => j !== i))}>✕</button>
                      </div>
                    </li>
                  );
                })}
                {lines.length === 1 && lines[0] === "" ? <li className="kit-muted at-small">Empty. Add blocks from the list.</li> : null}
              </ol>
            ) : (
              <textarea
                ref={area}
                className={`at-area${problems.length ? " is-bad" : ""}`}
                value={body}
                spellCheck={false}
                rows={14}
                onChange={(e) => setBody(e.target.value)}
                aria-label="Template text"
              />
            )}
            <div className="at-help">
              <span>
                <code>**bold**</code> <code>_italic_</code> · a plain <code>_</code> or <code>*</code> is <code>\_</code> <code>\*</code>
              </span>
              {preview ? (
                <span className={over ? "at-count is-over" : "at-count"}>
                  {preview.length.toLocaleString()} / {preview.limit.toLocaleString()}
                </span>
              ) : null}
            </div>
            <p className="kit-muted at-small">A line whose tags all come out empty is left out, so a missing league or a 0 - 0 stat doesn't leave a gap.</p>
            {problems.length ? (
              <ul className="at-problems">
                {problems.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            ) : null}
            <label className="at-toggle">
              <input type="checkbox" checked={enabled} onChange={(e) => setEnabledDrafts((prev) => ({ ...prev, [key]: e.target.checked }))} />
              Send this text (untick to keep it saved but use {isDefault ? "the built-in text" : "Default's text"})
            </label>
            <div className="rc-actions">
              <button type="button" className="kit-btn is-primary" disabled={busy || !dirty} onClick={() => void save()}>
                Save
              </button>
              <button type="button" className="kit-btn" disabled={busy || body === slot.body} onClick={() => setBody(slot.body)}>
                Undo changes
              </button>
              <button type="button" className="kit-btn" disabled={busy || (!slot.saved && body === slot.body)} onClick={() => void reset()}>
                {isDefault ? "Back to built-in" : "Back to Default"}
              </button>
              {isDefault ? null : (
                <button type="button" className="kit-btn" disabled={busy || body === builtIn} onClick={() => setBody(builtIn)} title="Start from the bot's built-in text">
                  Start from built-in
                </button>
              )}
              {status ? <p className="rc-status">{status}</p> : null}
            </div>
          </div>
        </article>

        <article className="kit-card at-preview">
          <div className="kit-card-head">
            <h2>Preview</h2>
            <div className="kit-card-right">
              <select
                className="at-select"
                value={sample ? chosen : "example"}
                onChange={(e) => setSampleIds((prev) => ({ ...prev, [sampleKey]: e.target.value }))}
                aria-label="Alert to preview with"
              >
                {own.length ? (
                  <optgroup label={isDefault ? "Recent" : `Recent ${strategyInfo?.short ?? ""} alerts`}>
                    {own.map((s) => (
                      <option key={s.ids.join("-")} value={s.ids.join("-")}>
                        {s.label}
                      </option>
                    ))}
                  </optgroup>
                ) : null}
                {others.length ? (
                  <optgroup label={`Other alerts, shown as ${strategyInfo?.short ?? ""}`}>
                    {others.map((s) => (
                      <option key={s.ids.join("-")} value={s.ids.join("-")}>
                        {s.label}
                      </option>
                    ))}
                  </optgroup>
                ) : null}
                <option value="example">Made-up example (long names)</option>
              </select>
            </div>
          </div>
          <div className="kit-card-body at-preview-body">
            {previewError ? <p className="kit-error">{previewError}</p> : null}
            {preview?.fell_back ? <p className="at-warn at-block">This one would go out with the fallback text: {preview.fell_back}</p> : null}
            {preview && showTelegram ? (
              <section>
                <div className="rc-cap">Telegram</div>
                <div className="at-bubble at-tg">
                  {activeKind === "alert" ? <div className="at-photo">Banner image</div> : <div className="at-quote">Reply to the alert</div>}
                  <div className="at-text">
                    <TelegramText html={preview.telegram} />
                  </div>
                </div>
              </section>
            ) : null}
            {preview && showDiscord ? (
              <section>
                <div className="rc-cap">Discord{channel !== "discord" ? " (same text, Discord has none of its own)" : ""}</div>
                <div className="at-bubble at-dc">
                  <div className="at-text">
                    <DiscordText text={preview.discord} />
                  </div>
                </div>
              </section>
            ) : null}
            {preview && preview.x ? (
              <section>
                <div className="rc-cap">
                  X{!isX ? " (same text, X has none of its own)" : ""}
                  <span className={`at-count${preview.x_weight > 280 ? " is-over" : ""}`}> · {preview.x_weight} / 280</span>
                </div>
                <div className="at-bubble at-x">
                  {activeKind === "alert" ? <div className="at-photo">Banner image</div> : <div className="at-quote">Reply to the alert tweet</div>}
                  <div className="at-text">{preview.x}</div>
                </div>
                {preview.x_dropped.length ? (
                  <div className="at-dropped">
                    <span>Dropped to fit one tweet:</span>
                    {preview.x_dropped.map((line, i) => (
                      <s key={`${i}-${line}`}>{line}</s>
                    ))}
                  </div>
                ) : activeKind !== "alert" && preview.x_weight > 280 ? (
                  <p className="kit-muted at-small">Over 280: a reply this long goes out as two tweets.</p>
                ) : null}
              </section>
            ) : null}
            {preview?.example ? <p className="kit-muted at-small">No recent alert to show, so this uses a made-up one.</p> : null}
          </div>
        </article>

        <aside className="kit-card at-tags">
          <div className="kit-card-head">
            <h2>{mode === "blocks" ? "Add a block" : "Tags"}</h2>
          </div>
          <div className="kit-card-body">
            {mode === "blocks" ? (
              <>
                {pieceGroups.map((group) => {
                  const span = group.pieces[0]?.span;
                  const chips = (
                    <ul className="at-pieces">
                      {group.pieces.map((piece) => {
                        const value = lineValue(piece.line, preview?.values);
                        const empty = value === "";
                        const title = empty
                          ? `${piece.line}\nEmpty on this alert (missing${piece.span ? " or 0 - 0" : ""}), so the line would be left out.`
                          : value
                            ? `${piece.line}\nOn this alert:\n${value}`
                            : piece.line;
                        return (
                          <li key={piece.key}>
                            <button
                              type="button"
                              className={`at-piece${used.has(piece.line) ? " is-used" : ""}${empty ? " is-empty" : ""}`}
                              onClick={() => addLine(piece.line)}
                              title={title}
                            >
                              <span>+</span> {piece.label}
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                  );
                  if (span === "auto") {
                    return (
                      <details key={group.name} className="at-tag-group at-follows">
                        <summary>
                          <h3>{group.name}</h3>
                        </summary>
                        <p className="at-group-note">{SPANS.auto.note}</p>
                        {chips}
                      </details>
                    );
                  }
                  return (
                    <div key={group.name} className="at-tag-group">
                      {span ? (
                        <>
                          <h3 className={`at-span at-span-${span}`}>{group.name}</h3>
                          <p className="at-group-note">{SPANS[span].note}</p>
                        </>
                      ) : (
                        <h3>{group.name}</h3>
                      )}
                      {chips}
                    </div>
                  );
                })}
                <div className="at-tag-group">
                  <h3>Layout</h3>
                  <ul className="at-pieces">
                    <li>
                      <button type="button" className="at-piece" onClick={() => addLine("")}>
                        <span>+</span> Blank line
                      </button>
                    </li>
                    <li>
                      <button type="button" className="at-piece" onClick={() => addLine("Your text")}>
                        <span>+</span> Your own line
                      </button>
                    </li>
                  </ul>
                </div>
                <p className="kit-muted at-small">
                  Hover a block to see what it says on the previewed alert; dashed ones have nothing to show there. Each block is one line. Edit its text to add words, emoji or **bold**; any tag from the Text view works in it.
                </p>
              </>
            ) : (
              <>
                {tagGroups.map((group) => (
                  <div key={group.name} className="at-tag-group">
                    <h3>{group.name}</h3>
                    <ul>
                      {group.tags.map((tag) => (
                        <li key={tag.name}>
                          <button type="button" className="at-tag" onClick={() => insertTag(tag.name)} title={`Example: ${tag.example}`}>
                            {`{${tag.name}}`}
                          </button>
                          <span>{tag.label}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
                <p className="kit-muted at-small">Kickoff time isn't recorded on alerts yet, so there's no tag for it.</p>
              </>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
