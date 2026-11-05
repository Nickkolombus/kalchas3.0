/**
 * Browser goal alerts for pinned matches.
 *
 * Turning them on asks for notification permission, registers /sw.js,
 * subscribes through the browser's push service and sends the subscription
 * plus the pinned match ids to /api/push/subscription. While on, every change
 * to the pins is sent again, so the server always knows what to alert on.
 * The bot sends the actual notifications, even with the site closed.
 */

import { useCallback, useEffect, useRef, useState } from "react";

export type GoalAlertState =
  | "loading"
  /** Server has no push key or this browser cannot do push: show nothing. */
  | "hidden"
  /** iPhone/iPad Safari tab: push only works from the home-screen app. */
  | "needs-install"
  | "blocked"
  | "off"
  | "busy"
  | "on";

type PushConfig = { enabled: boolean; public_key: string | null };

const SW_URL = "/sw.js";

function isIos(): boolean {
  const ua = navigator.userAgent || "";
  // iPadOS reports itself as a Mac with touch.
  return /iPhone|iPad|iPod/.test(ua) || (ua.includes("Macintosh") && navigator.maxTouchPoints > 1);
}

function isStandalone(): boolean {
  return (
    window.matchMedia?.("(display-mode: standalone)").matches ||
    (navigator as Navigator & { standalone?: boolean }).standalone === true
  );
}

function pushCapable(): boolean {
  return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

function keyBytes(base64url: string): Uint8Array<ArrayBuffer> {
  const padded = base64url.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(base64url.length / 4) * 4, "=");
  const raw = atob(padded);
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i += 1) out[i] = raw.charCodeAt(i);
  return out;
}

async function currentSubscription(): Promise<PushSubscription | null> {
  const reg = await navigator.serviceWorker.getRegistration(SW_URL);
  return reg ? reg.pushManager.getSubscription() : null;
}

async function sendSubscription(sub: PushSubscription, matchIds: string[]): Promise<void> {
  const json = sub.toJSON();
  const res = await fetch("/api/push/subscription", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ endpoint: json.endpoint, keys: json.keys, match_ids: matchIds }),
  });
  if (!res.ok) throw new Error(`push subscription ${res.status}`);
}

export function useGoalAlerts(favorites: Set<string>) {
  const [state, setState] = useState<GoalAlertState>("loading");
  const [publicKey, setPublicKey] = useState<string | null>(null);
  const subRef = useRef<PushSubscription | null>(null);
  const idsRef = useRef<string[]>([]);
  idsRef.current = [...favorites];

  // What can this browser do, and is it already subscribed?
  useEffect(() => {
    let cancelled = false;
    (async () => {
      let config: PushConfig = { enabled: false, public_key: null };
      try {
        const res = await fetch("/api/push/config");
        if (res.ok) config = (await res.json()) as PushConfig;
      } catch {
        // No server push: stay hidden.
      }
      if (cancelled) return;
      if (!config.enabled || !config.public_key) return setState("hidden");
      setPublicKey(config.public_key);
      if (!pushCapable()) return setState(isIos() && !isStandalone() ? "needs-install" : "hidden");
      if (Notification.permission === "denied") return setState("blocked");
      try {
        const sub = Notification.permission === "granted" ? await currentSubscription() : null;
        if (cancelled) return;
        subRef.current = sub;
        if (sub) {
          // Refresh the server copy: pins may have changed while the site was closed.
          await sendSubscription(sub, idsRef.current).catch(() => undefined);
        }
        setState(sub ? "on" : "off");
      } catch {
        setState("off");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Keep the server's follow list in step with the pins.
  const favKey = [...favorites].sort().join(",");
  useEffect(() => {
    if (state !== "on" || !subRef.current) return;
    const sub = subRef.current;
    const timer = window.setTimeout(() => {
      void sendSubscription(sub, idsRef.current).catch(() => undefined);
    }, 500);
    return () => window.clearTimeout(timer);
  }, [favKey, state]);

  const enable = useCallback(async () => {
    if (!publicKey || state === "busy") return;
    setState("busy");
    try {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        setState(permission === "denied" ? "blocked" : "off");
        return;
      }
      await navigator.serviceWorker.register(SW_URL, { scope: "/" });
      const reg = await navigator.serviceWorker.ready;
      let sub = await reg.pushManager.getSubscription();
      if (!sub) {
        sub = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: keyBytes(publicKey),
        });
      }
      await sendSubscription(sub, idsRef.current);
      subRef.current = sub;
      setState("on");
    } catch {
      setState("off");
    }
  }, [publicKey, state]);

  const disable = useCallback(async () => {
    const sub = subRef.current;
    setState("busy");
    try {
      if (sub) {
        await fetch("/api/push/subscription", {
          method: "DELETE",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ endpoint: sub.endpoint }),
        }).catch(() => undefined);
        await sub.unsubscribe();
      }
    } finally {
      subRef.current = null;
      setState("off");
    }
  }, []);

  return { state, enable, disable };
}
