import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

const HOVER_SHOW_DELAY_MS = 420;

export type HoverScale = { min: number; max: number };

export function hoverLead(
  home?: { value?: number; triggered?: boolean },
  away?: { value?: number; triggered?: boolean },
): { home: boolean; away: boolean } {
  if (home?.triggered || away?.triggered) {
    return { home: Boolean(home?.triggered), away: Boolean(away?.triggered) };
  }
  const hv = home?.value;
  const av = away?.value;
  if (hv == null || av == null || Number.isNaN(hv) || Number.isNaN(av) || hv === av) {
    return { home: false, away: false };
  }
  return { home: hv > av, away: av > hv };
}

export function hoverBarPct(
  value: number | undefined | null,
  scale?: HoverScale,
): number | null {
  if (scale == null || value == null || Number.isNaN(value)) return null;
  const span = scale.max - scale.min;
  if (span <= 0) return null;
  return Math.min(100, Math.max(0, ((value - scale.min) / span) * 100));
}

function HoverRow({
  name,
  value,
  lead,
  pct,
}: {
  name: string;
  value: string;
  lead?: boolean;
  pct?: number | null;
}) {
  return (
    <div className="hover-row">
      <span className={`hover-dot${lead ? " is-lead" : ""}`} />
      <span className="hover-row-name">{name}</span>
      <span className="hover-row-val">{value}</span>
      {pct != null ? (
        <div className="hover-mini" aria-hidden>
          <i style={{ width: `${pct}%` }} />
        </div>
      ) : null}
    </div>
  );
}

export function HoverLedger({
  tip,
  homeName,
  awayName,
  homeValue,
  awayValue,
  homeLead,
  awayLead,
  homePct,
  awayPct,
  extra,
}: {
  tip: string;
  homeName: string;
  awayName: string;
  homeValue: string;
  awayValue: string;
  homeLead?: boolean;
  awayLead?: boolean;
  homePct?: number | null;
  awayPct?: number | null;
  extra?: ReactNode;
}) {
  return (
    <>
      <p>{tip}</p>
      {extra}
      <div className="hover-ledger">
        <HoverRow name={homeName} value={homeValue} lead={homeLead} pct={homePct} />
        <HoverRow name={awayName} value={awayValue} lead={awayLead} pct={awayPct} />
      </div>
    </>
  );
}

export function HoverTip({
  title,
  body,
  children,
  cardClass,
}: {
  title: string;
  body: ReactNode;
  children: ReactNode;
  cardClass?: string;
}) {
  const anchorRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const timerRef = useRef<number | null>(null);
  const [open, setOpen] = useState(false);
  const [coords, setCoords] = useState({ top: 0, left: 0 });
  const [placed, setPlaced] = useState(false);

  const clearTimer = useCallback(() => {
    if (timerRef.current != null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const place = useCallback(() => {
    const anchor = anchorRef.current;
    const card = cardRef.current;
    if (!anchor || !card) return;
    const rect = anchor.getBoundingClientRect();
    const cardRect = card.getBoundingClientRect();
    const gap = 10;
    const pad = 8;
    let left = rect.left + rect.width / 2 - cardRect.width / 2;
    left = Math.min(Math.max(pad, left), window.innerWidth - cardRect.width - pad);
    let top = rect.top - cardRect.height - gap;
    if (top < pad) top = rect.bottom + gap;
    setCoords({ top, left });
    setPlaced(true);
  }, []);

  useLayoutEffect(() => {
    if (!open) {
      setPlaced(false);
      return;
    }
    place();
  }, [open, place, title]);

  useEffect(() => () => clearTimer(), [clearTimer]);

  return (
    <div
      className="hover-anchor"
      ref={anchorRef}
      onMouseEnter={() => {
        clearTimer();
        timerRef.current = window.setTimeout(() => {
          timerRef.current = null;
          setOpen(true);
        }, HOVER_SHOW_DELAY_MS);
      }}
      onMouseLeave={() => {
        clearTimer();
        setOpen(false);
      }}
    >
      {children}
      {open
        ? createPortal(
            <div
              ref={cardRef}
              className={`hover-card${placed ? " is-in" : ""}${cardClass ? ` ${cardClass}` : ""}`}
              role="tooltip"
              style={{
                top: coords.top,
                left: coords.left,
                visibility: placed ? "visible" : "hidden",
              }}
            >
              <div className="hover-title">{title}</div>
              <div className="hover-body">{body}</div>
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}
