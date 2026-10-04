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

export function HoverTip({
  title,
  body,
  children,
}: {
  title: string;
  body: ReactNode;
  children: ReactNode;
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
              className={`hover-card${placed ? " is-in" : ""}`}
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
