import { useCallback, useEffect, useState } from "react";
import "./styles/contact.css";
import type { Api } from "./AdminKit";

type Message = {
  id: number;
  created_at: string | null;
  name: string;
  email: string;
  message: string;
  ip_masked: string | null;
  country: string | null;
  emailed: boolean;
  telegram_sent: boolean;
};

type Payload = {
  messages: Message[];
  to?: string;
  email_ready: boolean;
  telegram_ready: boolean;
};

function fmtWhen(iso: string | null, zone: string): string {
  if (!iso) return "";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  return at.toLocaleString(undefined, {
    timeZone: zone,
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function AdminMessages({ api, zone }: { api: Api; zone: string }) {
  const [body, setBody] = useState<Payload | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      setBody(await api<Payload>("/api/admin/contact"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "load failed");
    }
  }, [api]);

  useEffect(() => {
    void load();
  }, [load]);

  const missing = body
    ? [
        body.email_ready ? null : "RESEND_API_KEY isn't set, so messages are not being emailed.",
        body.telegram_ready
          ? null
          : "No Telegram chat is set (CONTACT_TELEGRAM_CHAT_ID or RECAP_ADMIN_CHAT_ID), so there are no pings.",
      ].filter((line): line is string => line != null)
    : [];

  return (
    <div className="msg-page">
      <article className="kit-card">
        <div className="kit-card-head">
          <h2>Contact form</h2>
          <span className="kit-sub">
            From the “Contact us” link on the board. Emailed to {body?.to ?? "info@kalchas.live"}.
          </span>
          <div className="kit-card-right">
            <button type="button" className="kit-btn" onClick={() => void load()}>
              Refresh
            </button>
          </div>
        </div>
        <div className="kit-card-body">
          {missing.map((line) => (
            <p key={line} className="msg-warn">
              {line}
            </p>
          ))}
          {error ? <p className="kit-error">{error}</p> : null}
          {body && body.messages.length === 0 ? (
            <p className="kit-empty">No messages yet.</p>
          ) : null}
          <ul className="msg-list">
            {(body?.messages ?? []).map((m) => (
              <li key={m.id} className="msg-item">
                <div className="msg-meta">
                  <b>{m.name}</b>
                  <span className="kit-muted">{m.email}</span>
                  <span className="msg-when kit-muted">
                    {fmtWhen(m.created_at, zone)}
                    {m.country ? ` · ${m.country}` : ""}
                  </span>
                </div>
                <p className="msg-text">{m.message}</p>
                <div className="msg-flags">
                  <span className={`kit-pill ${m.emailed ? "is-ok" : "is-miss"}`}>
                    {m.emailed ? "Emailed" : "Not emailed"}
                  </span>
                  <span className={`kit-pill ${m.telegram_sent ? "is-ok" : "is-miss"}`}>
                    {m.telegram_sent ? "Telegram sent" : "No Telegram"}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </article>
    </div>
  );
}
