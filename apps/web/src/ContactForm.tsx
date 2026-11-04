import { useEffect, useRef, useState, type FormEvent } from "react";
import "./styles/contact.css";

// Mirrors kalchas_api/contact.py so most mistakes are caught before sending.
const MAX_NAME = 80;
const MAX_EMAIL = 200;
const MIN_MESSAGE = 10;
const MAX_MESSAGE = 4000;
const EMAIL_RE = /^[^@\s<>"',;]+@[^@\s<>"',;]+\.[A-Za-z]{2,}$/;
const FALLBACK_ERROR = "We couldn't send your message just now. Please try again in a few minutes.";

type Status =
  | { kind: "idle" }
  | { kind: "sending" }
  | { kind: "sent"; email: string }
  | { kind: "error"; text: string };

function checkFields(name: string, email: string, message: string): string | null {
  if (!name.trim()) return "Please add your name.";
  if (name.trim().length > MAX_NAME) return `Please keep your name under ${MAX_NAME} characters.`;
  const mail = email.trim();
  if (!mail || mail.length > MAX_EMAIL || !EMAIL_RE.test(mail)) {
    return "Please check your email address.";
  }
  if (message.trim().length < MIN_MESSAGE) return "Please write a little more in your message.";
  if (message.trim().length > MAX_MESSAGE) {
    return `Please keep your message under ${MAX_MESSAGE} characters.`;
  }
  return null;
}

export function ContactDialog({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [website, setWebsite] = useState("");
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const openedAt = useRef(Date.now());
  const firstField = useRef<HTMLInputElement>(null);
  // The board re-renders on every poll; keep the latest onClose without
  // re-running the effect below (which would steal focus mid-typing).
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeRef.current();
    };
    window.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    firstField.current?.focus();
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (status.kind === "sending") return;
    const problem = checkFields(name, email, message);
    if (problem) {
      setStatus({ kind: "error", text: problem });
      return;
    }
    setStatus({ kind: "sending" });
    try {
      const res = await fetch("/api/contact", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          email,
          message,
          website,
          elapsed_ms: Date.now() - openedAt.current,
        }),
      });
      if (res.ok) {
        setStatus({ kind: "sent", email: email.trim() });
        return;
      }
      const body = (await res.json().catch(() => ({}))) as { detail?: unknown };
      // 400 and 429 carry a sentence meant for the visitor; anything else is ours.
      const text =
        (res.status === 400 || res.status === 429) && typeof body.detail === "string"
          ? body.detail
          : FALLBACK_ERROR;
      setStatus({ kind: "error", text });
    } catch {
      setStatus({ kind: "error", text: FALLBACK_ERROR });
    }
  }

  const sending = status.kind === "sending";
  const left = MAX_MESSAGE - message.length;

  return (
    <div
      className="overlay-backdrop contact-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="contact-card" role="dialog" aria-modal="true" aria-labelledby="contact-title">
        <div className="contact-head">
          <h2 id="contact-title">Contact us</h2>
          <button type="button" className="mp-close" onClick={onClose}>
            Close
          </button>
        </div>

        {status.kind === "sent" ? (
          <div className="contact-sent" role="status">
            <p className="contact-sent-title">Thanks, your message has been sent.</p>
            <p>
              We'll reply to <b>{status.email}</b>.
            </p>
            <button type="button" className="contact-submit" onClick={onClose}>
              Back to the board
            </button>
          </div>
        ) : (
          <form className="contact-form" onSubmit={(event) => void submit(event)} noValidate>
            <p className="contact-intro">
              Questions, feedback or a problem with the board or Telegram? Send us a note and
              we'll reply by email.
            </p>
            <label className="contact-field">
              <span>Name</span>
              <input
                ref={firstField}
                type="text"
                name="name"
                autoComplete="name"
                maxLength={MAX_NAME}
                value={name}
                onChange={(event) => setName(event.target.value)}
                disabled={sending}
                required
              />
            </label>
            <label className="contact-field">
              <span>Email</span>
              <input
                type="email"
                name="email"
                autoComplete="email"
                inputMode="email"
                maxLength={MAX_EMAIL}
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                disabled={sending}
                required
              />
            </label>
            <label className="contact-field">
              <span>Message</span>
              <textarea
                name="message"
                rows={6}
                maxLength={MAX_MESSAGE}
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                disabled={sending}
                required
              />
              {left < 500 ? <small className="contact-count">{left} characters left</small> : null}
            </label>
            {/* Hidden from people; form-filling bots tend to complete it. */}
            <label className="contact-trap" aria-hidden="true">
              Website
              <input
                type="text"
                name="website"
                tabIndex={-1}
                autoComplete="off"
                value={website}
                onChange={(event) => setWebsite(event.target.value)}
              />
            </label>

            {status.kind === "error" ? (
              <p className="contact-error" role="alert">
                {status.text}
              </p>
            ) : null}

            <div className="contact-actions">
              <button type="submit" className="contact-submit" disabled={sending}>
                {sending ? "Sending…" : "Send message"}
              </button>
              <span className="contact-note">Or email info@kalchas.live</span>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

export function ContactLink({ className }: { className?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className={className ?? "contact-link"} onClick={() => setOpen(true)}>
        Contact us
      </button>
      {open ? <ContactDialog onClose={() => setOpen(false)} /> : null}
    </>
  );
}

export function SiteFooter() {
  return (
    <footer className="site-foot">
      <span>Kalchas · Live Match Intelligence</span>
      <ContactLink />
    </footer>
  );
}
