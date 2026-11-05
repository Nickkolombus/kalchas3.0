import type { ReactNode } from "react";
import kalchasMark from "./assets/kalchas-mark.png";

/**
 * The live board's masthead: the mark, name, title and intro. The watchlist
 * pages show the very same one, so moving between them feels like one site.
 * Only the live board makes the title its page heading; the watchlist pages
 * have their own.
 */
export function BrandIdentity({ heading = true, children }: { heading?: boolean; children?: ReactNode }) {
  const Title = heading ? "h1" : "p";
  return (
    <div className="identity">
      <img className="mark" src={kalchasMark} alt="" width={96} height={96} />
      <div className="identity-text">
        <p className="brand">Kalchas</p>
        <Title className="hero-title">Live Match Intelligence</Title>
        <p className="lede">
          Live board of pressure and goal signals, free on this site. Free Telegram: Mon-Thu GMT, one alert per hour.
          Every fire goes to the full feed.
        </p>
        {children}
      </div>
    </div>
  );
}
