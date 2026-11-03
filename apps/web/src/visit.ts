/**
 * The anonymous visitor id (no account) and the small signals that feed the
 * admin visitor log: join-button and watchlist clicks, and the watchlist
 * pages' heartbeat.
 */

const VISITOR_ID_STORAGE_SLOT = "kalchas.visitor.v1";

export function visitorId(): string {
  try {
    const existing = localStorage.getItem(VISITOR_ID_STORAGE_SLOT);
    if (existing) return existing;
    const next =
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `v${Date.now()}${Math.random().toString(16).slice(2)}`;
    localStorage.setItem(VISITOR_ID_STORAGE_SLOT, next);
    return next;
  } catch {
    return "";
  }
}

export type VisitEvent =
  | "tg_free"
  | "tg_paid"
  /** Ways into the watchlist from the live board. */
  | "wl_hero"
  | "wl_board"
  | "wl_panel"
  | "wl_tab"
  /** What they opened once inside. */
  | "wl_match"
  | "wl_calendar"
  | "wl_tomorrow"
  | "wl_past";

function post(url: string, body: string): void {
  try {
    // A beacon is fire-and-forget, so the click is logged even if the page
    // is being left (every watchlist link is a full page load).
    if (navigator.sendBeacon?.(url, new Blob([body], { type: "application/json" }))) return;
  } catch {
    // Fall through to fetch.
  }
  void fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    keepalive: true,
  }).catch(() => undefined);
}

export function logVisitEvent(kind: VisitEvent, visitor = visitorId()): void {
  if (!visitor) return;
  post("/api/visit/event", JSON.stringify({ vid: visitor, kind }));
}

/** Keeps the visit going from pages that don't poll the live board. The
 * first ping carries the referrer and resolves once the visit exists, so
 * events sent after it have a visit to land on. */
export function pingVisit(visitor: string, referrer?: string): Promise<void> {
  if (!visitor) return Promise.resolve();
  return fetch("/api/visit/ping", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ vid: visitor, ref: referrer || null }),
    keepalive: true,
  })
    .then(() => undefined)
    .catch(() => undefined);
}
