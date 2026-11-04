import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import "./styles/alert-text.css";
import type { Api } from "./AdminKit";

type Channel = "paid" | "free" | "discord";
type Kind = "alert" | "goal";

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

type Sample = { ids: number[]; label: string };

type Payload = {
  templates: Record<Channel, Record<Kind, Slot>>;
  defaults: Record<Kind, string>;
  tags: Tag[];
  samples: Record<Kind, Sample[]>;
};

type Preview = {
  problems: string[];
  telegram: string;
  discord: string;
  x: string;
  length: number;
  limit: number;
  fell_back: string | null;
  discord_follows: boolean;
  example: boolean;
};

const CHANNELS: { key: Channel; label: string; note: string }[] = [
  { key: "paid", label: "Telegram paid", note: "The paid channel. Discord's paid channel gets the same text unless the Discord template is on." },
  { key: "free", label: "Telegram free", note: "The free channel. X posts this text too (no bold or italics there), and Discord's free channel unless the Discord template is on." },
  { key: "discord", label: "Discord", note: "Used for both Discord channels when switched on. When it's off, Discord gets the matching Telegram text." },
];

const KINDS: { key: Kind; label: string; note: string }[] = [
  { key: "alert", label: "Alert", note: "Sent under the banner image when a signal fires. If a second strategy fires on the same minute, the message is edited to show both." },
  { key: "goal", label: "Goal reply", note: "Sent as a reply under the alert when a goal comes. A miss is only a 😢 reaction, so it has no text to edit." },
];

function slotKey(channel: Channel, kind: Kind): string {
  return `${channel}/${kind}`;
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

export function AdminAlertText({ api }: { api: Api }) {
  const [data, setData] = useState<Payload | null>(null);
  const [error, setError] = useState("");
  const [channel, setChannel] = useState<Channel>("paid");
  const [kind, setKind] = useState<Kind>("alert");
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [enabledDrafts, setEnabledDrafts] = useState<Record<string, boolean>>({});
  const [sampleIdx, setSampleIdx] = useState<Record<Kind, number>>({ alert: 0, goal: 0 });
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewError, setPreviewError] = useState("");
  const [saveProblems, setSaveProblems] = useState<string[]>([]);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
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

  const key = slotKey(channel, kind);
  const slot = data?.templates[channel][kind] ?? null;
  const body = drafts[key] ?? slot?.body ?? "";
  const enabled = enabledDrafts[key] ?? (slot ? (slot.saved ? slot.enabled : true) : true);
  const dirty = slot != null && (body !== slot.body || enabled !== (slot.saved ? slot.enabled : true) || !slot.saved);
  const samples = data?.samples[kind] ?? [];
  const sample = samples[sampleIdx[kind]] ?? null;

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
          body: JSON.stringify({ channel, kind, body, ids: sample?.ids ?? [] }),
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
  }, [api, data, channel, kind, body, sample]);

  const tagGroups = useMemo(() => {
    const groups: { name: string; tags: Tag[] }[] = [];
    for (const tag of data?.tags ?? []) {
      if (!tag.kinds.includes(kind)) continue;
      let group = groups.find((g) => g.name === tag.group);
      if (!group) {
        group = { name: tag.group, tags: [] };
        groups.push(group);
      }
      group.tags.push(tag);
    }
    // Goal-only tags first on the goal reply: they're the reason to be there.
    if (kind === "goal") groups.sort((a, b) => (a.name === "Goal reply" ? -1 : b.name === "Goal reply" ? 1 : 0));
    return groups;
  }, [data, kind]);

  function setBody(next: string) {
    setDrafts((prev) => ({ ...prev, [key]: next }));
    setStatus("");
  }

  function insertTag(name: string) {
    const el = area.current;
    const token = `{${name}}`;
    if (!el) {
      setBody(body + token);
      return;
    }
    const start = el.selectionStart ?? body.length;
    const end = el.selectionEnd ?? body.length;
    const next = body.slice(0, start) + token + body.slice(end);
    setBody(next);
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(start + token.length, start + token.length);
    });
  }

  async function save() {
    setBusy(true);
    setSaveProblems([]);
    setStatus("");
    try {
      const res = await fetch(`/api/admin/alert-templates/${channel}/${kind}`, {
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
      await load();
      setStatus(enabled ? "Saved. The bot uses it from the next alert." : "Saved, switched off. The bot keeps sending the built-in text.");
    } catch (err) {
      setSaveProblems([err instanceof Error ? err.message : "save failed"]);
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    if (!window.confirm("Delete this template and go back to the built-in text?")) return;
    setBusy(true);
    try {
      if (slot?.saved) {
        await api(`/api/admin/alert-templates/${channel}/${kind}`, { method: "DELETE" });
      }
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
      await load();
      setStatus("Back to the built-in text.");
    } catch (err) {
      setSaveProblems([err instanceof Error ? err.message : "reset failed"]);
    } finally {
      setBusy(false);
    }
  }

  if (error) return <p className="kit-error">{error}</p>;
  if (!data || !slot) return <p className="kit-muted">Loading…</p>;

  const live = slot.saved && slot.enabled;
  const channelInfo = CHANNELS.find((c) => c.key === channel)!;
  const kindInfo = KINDS.find((k) => k.key === kind)!;
  const problems = saveProblems.length ? saveProblems : (preview?.problems ?? []);
  const over = preview != null && preview.length > preview.limit;
  const showTelegram = channel !== "discord";
  const showDiscord = channel === "discord" || preview?.discord_follows !== false;

  return (
    <div className="at">
      <article className="kit-card at-bar">
        <div className="at-switch">
          <div className="rc-tabs" role="tablist" aria-label="Channel">
            {CHANNELS.map((c) => (
              <button key={c.key} type="button" className={c.key === channel ? "is-on" : ""} onClick={() => setChannel(c.key)}>
                {c.label}
                {data.templates[c.key].alert.saved && data.templates[c.key].alert.enabled ? <span className="at-dot" title="Alert template on" /> : null}
              </button>
            ))}
          </div>
          <div className="rc-tabs" role="tablist" aria-label="Message">
            {KINDS.map((k) => (
              <button key={k.key} type="button" className={k.key === kind ? "is-on" : ""} onClick={() => setKind(k.key)}>
                {k.label}
                {data.templates[channel][k.key].saved && data.templates[channel][k.key].enabled ? <span className="at-dot" title="Template on" /> : null}
              </button>
            ))}
          </div>
        </div>
        <p className="at-note">
          {channelInfo.note} {kindInfo.note}
        </p>
        <div className="at-state">
          <span className={`kit-pill ${live ? "is-ok" : "is-open"}`}>
            <i>{live ? "●" : "○"}</i>
            {live ? "Your template is in use" : slot.saved ? "Saved but switched off: built-in text in use" : "Built-in text in use"}
          </span>
          {slot.updated_at ? <span className="kit-muted">Saved {fmtWhen(slot.updated_at)}</span> : null}
          {slot.fallback_count > 0 ? (
            <span className="at-warn">
              Built-in text went out instead {slot.fallback_count} {slot.fallback_count === 1 ? "time" : "times"} since saving
              {slot.last_fallback_at ? `, last ${fmtWhen(slot.last_fallback_at)}` : ""}
              {slot.last_fallback_reason ? `: ${slot.last_fallback_reason}` : ""}
            </span>
          ) : null}
        </div>
      </article>

      <div className="at-grid">
        <article className="kit-card at-edit">
          <div className="kit-card-head">
            <h2>Template</h2>
            <span className="kit-sub">Click a tag in the list to add it where the cursor is.</span>
          </div>
          <div className="kit-card-body at-edit-body">
            <textarea
              ref={area}
              className={`at-area${problems.length ? " is-bad" : ""}`}
              value={body}
              spellCheck={false}
              rows={12}
              onChange={(e) => setBody(e.target.value)}
              aria-label="Template text"
            />
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
            <p className="kit-muted at-small">
              A line whose tags are all empty is left out, so a missing league doesn't leave a blank line.
            </p>
            {problems.length ? (
              <ul className="at-problems">
                {problems.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            ) : null}
            <label className="at-toggle">
              <input type="checkbox" checked={enabled} onChange={(e) => setEnabledDrafts((prev) => ({ ...prev, [key]: e.target.checked }))} />
              Send this text (untick to keep it saved but use the built-in text)
            </label>
            <div className="rc-actions">
              <button type="button" className="kit-btn is-primary" disabled={busy || !dirty} onClick={() => void save()}>
                Save
              </button>
              <button
                type="button"
                className="kit-btn"
                disabled={busy || body === (slot.saved ? slot.body : data.defaults[kind])}
                onClick={() => setBody(slot.saved ? slot.body : data.defaults[kind])}
              >
                Undo changes
              </button>
              <button type="button" className="kit-btn" disabled={busy || (!slot.saved && body === data.defaults[kind])} onClick={() => void reset()}>
                Back to built-in
              </button>
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
                value={sampleIdx[kind]}
                onChange={(e) => setSampleIdx((prev) => ({ ...prev, [kind]: Number(e.target.value) }))}
                aria-label="Alert to preview with"
              >
                {samples.map((s, i) => (
                  <option key={s.ids.join("-")} value={i}>
                    {s.label}
                  </option>
                ))}
                <option value={samples.length}>Made-up example (long names)</option>
              </select>
            </div>
          </div>
          <div className="kit-card-body at-preview-body">
            {previewError ? <p className="kit-error">{previewError}</p> : null}
            {preview?.fell_back ? (
              <p className="at-warn at-block">
                This one would go out with the built-in text: {preview.fell_back}
              </p>
            ) : null}
            {preview && showTelegram ? (
              <section>
                <div className="rc-cap">Telegram</div>
                <div className="at-bubble at-tg">
                  {kind === "alert" ? <div className="at-photo">Banner image</div> : <div className="at-quote">Reply to the alert</div>}
                  <div className="at-text">
                    <TelegramText html={preview.telegram} />
                  </div>
                </div>
              </section>
            ) : null}
            {preview && showDiscord ? (
              <section>
                <div className="rc-cap">
                  Discord{channel !== "discord" ? " (same text, Discord template is off)" : ""}
                </div>
                <div className="at-bubble at-dc">
                  <div className="at-text">
                    <DiscordText text={preview.discord} />
                  </div>
                </div>
              </section>
            ) : null}
            {preview && preview.x ? (
              <section>
                <div className="rc-cap">X (split into a thread past 280 characters)</div>
                <div className="at-bubble at-x">
                  <div className="at-text">{preview.x}</div>
                </div>
              </section>
            ) : null}
            {preview?.example ? <p className="kit-muted at-small">No recent alert to show, so this uses a made-up one.</p> : null}
          </div>
        </article>

        <aside className="kit-card at-tags">
          <div className="kit-card-head">
            <h2>Tags</h2>
          </div>
          <div className="kit-card-body">
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
            <p className="kit-muted at-small">
              Kickoff time isn't recorded on alerts yet, so there's no tag for it.
            </p>
          </div>
        </aside>
      </div>
    </div>
  );
}
