import { useState } from "react";
import type { MouseEvent } from "react";
import type { GoalAlertState } from "./goalAlerts";

function BellIcon() {
  return (
    <svg className="goal-alert-bell" viewBox="0 0 16 16" width="11" height="11" aria-hidden="true">
      <path
        d="M8 1.75a4 4 0 0 0-4 4v2.6L2.75 10.6v.9h10.5v-.9L12 8.35v-2.6a4 4 0 0 0-4-4ZM6.4 12.75a1.6 1.6 0 0 0 3.2 0"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** Switch on the Pinned shelf: browser notification when a pinned match scores. */
export function GoalAlertToggle({
  state,
  onEnable,
  onDisable,
}: {
  state: GoalAlertState;
  onEnable: () => void;
  onDisable: () => void;
}) {
  const [showInstallTip, setShowInstallTip] = useState(false);
  if (state === "hidden" || state === "loading") return null;

  const stop = (e: MouseEvent) => e.stopPropagation();

  if (state === "blocked") {
    return (
      <span className="goal-alert goal-alert-note" title="Allow notifications for kalchas.live in your browser settings">
        <BellIcon /> Goal alerts blocked in browser settings
      </span>
    );
  }

  if (state === "needs-install") {
    return (
      <span className="goal-alert-wrap">
        <button
          type="button"
          className="goal-alert"
          onClick={(e) => {
            stop(e);
            setShowInstallTip((v) => !v);
          }}
        >
          <BellIcon /> Goal alerts
        </button>
        {showInstallTip ? (
          <span className="goal-alert-tip">
            On iPhone: tap Share, then Add to Home Screen, and open Kalchas from there.
          </span>
        ) : null}
      </span>
    );
  }

  const on = state === "on";
  return (
    <button
      type="button"
      className={`goal-alert${on ? " is-on" : ""}`}
      disabled={state === "busy"}
      aria-pressed={on}
      title={on ? "You get a notification when a pinned match scores. Click to stop." : "Get a notification when a pinned match scores, even with this site closed."}
      onClick={(e) => {
        stop(e);
        if (on) onDisable();
        else onEnable();
      }}
    >
      <BellIcon /> {state === "busy" ? "One moment…" : on ? "Goal alerts on" : "Alert me on goals"}
    </button>
  );
}
