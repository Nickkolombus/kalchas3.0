import { useCallback, useEffect, useState } from "react";
import {
  Card,
  Delta,
  LineChart,
  Legend,
  StackedBars,
  StatStrip,
  fmtDay,
  fmtInt,
  fmtShort,
  pct,
  type Api,
} from "./AdminKit";
import type { AlertStats, StrategyMeta } from "./AdminResults";
import type { VisitStats } from "./AdminVisitors";

type Attention = { level: "warn" | "info" | "ok"; title: string; detail: string; go: string };

type OverviewPayload = {
  date: string;
  names: Record<string, string>;
  results: { today: AlertStats; yesterday: AlertStats };
  visitors: { today: VisitStats; yesterday: VisitStats };
  live_now: number | null;
  strategies: { strategy: string; today: AlertStats; month: AlertStats }[];
  hit_daily: { date: string; total: number; confirmed: number; settled: number; hit_rate: number | null }[];
  visitor_daily: { date: string; new: number; returning: number }[];
  attention: Attention[];
};

export type DiscordState = {
  free_channel_id: string | null;
  paid_channel_id: string | null;
  free_enabled: boolean;
  paid_enabled: boolean;
};

const ICON: Record<Attention["level"], string> = { warn: "!", info: "↗", ok: "✓" };

// Settings problems the config already tells us about, no extra request needed.
function configAttention(strategies: StrategyMeta[], discord: DiscordState): Attention[] {
  const out: Attention[] = [];
  for (const [label, id, on] of [
    ["Paid", discord.paid_channel_id, discord.paid_enabled],
    ["Free", discord.free_channel_id, discord.free_enabled],
  ] as const) {
    if (!id) {
      out.push({ level: "warn", title: `${label} Discord channel has no channel id`, detail: `Fires are not cross-posted to the ${label.toLowerCase()} channel.`, go: "discord" });
    } else if (!on) {
      out.push({ level: "warn", title: `${label} Discord cross-posting is switched off`, detail: "The channel id is set but the kill switch is on.", go: "discord" });
    }
  }
  const off = strategies.filter((s) => !s.enabled);
  if (off.length) {
    out.push({
      level: "info",
      title: `${off.map((s) => s.short).join(", ")} ${off.length === 1 ? "is" : "are"} disabled`,
      detail: "Disabled strategies do not fire. Older alerts still show in Results.",
      go: `strategies:${off[0].key}`,
    });
  }
  return out;
}

export function AdminOverview({
  api,
  zone,
  strategies,
  discord,
  onGo,
}: {
  api: Api;
  zone: string;
  strategies: StrategyMeta[];
  discord: DiscordState;
  onGo: (spec: string) => void;
}) {
  const [body, setBody] = useState<OverviewPayload | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      setBody(await api<OverviewPayload>(`/api/admin/insights/overview?tz=${encodeURIComponent(zone)}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "load failed");
    }
  }, [api, zone]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 60_000);
    return () => window.clearInterval(timer);
  }, [load]);

  if (!body) return <p className="kit-empty">{error || "Loading today…"}</p>;

  const R = body.results;
  const V = body.visitors;
  const short = (key: string) => strategies.find((s) => s.key === key)?.short || body.names[key] || key;
  const order: Record<Attention["level"], number> = { warn: 0, info: 1, ok: 2 };
  const attention = [...body.attention, ...configAttention(strategies, discord)].sort(
    (a, b) => order[a.level] - order[b.level],
  );
  const fortnightSettled = body.hit_daily.reduce((s, d) => s + d.settled, 0);
  const fortnightHits = body.hit_daily.reduce((s, d) => s + d.confirmed, 0);

  return (
    <>
      {error ? <p className="kit-error">{error}</p> : null}
      <StatStrip
        minWidth={130}
        stats={[
          {
            label: "Hit rate",
            hero: true,
            value: pct(R.today.hit_rate),
            foot: <Delta cur={R.today.hit_rate} prev={R.yesterday.hit_rate} pts label="vs yday" />,
          },
          {
            label: "Alerts",
            value: (
              <>
                {fmtInt(R.today.total)}
                <small>{R.today.open} open</small>
              </>
            ),
            foot: <Delta cur={R.today.total} prev={R.yesterday.total} label="vs yday" />,
          },
          {
            label: "Visitors",
            value: fmtInt(V.today.visitors),
            foot: <Delta cur={V.today.visitors} prev={V.yesterday.visitors} label="vs yday" />,
          },
          {
            label: "Live now",
            value: (
              <span className="ov-live">
                {body.live_now ?? "–"}
                <i />
              </span>
            ),
            foot: <span className="kit-delta">on the board</span>,
          },
          {
            label: "Telegram clicks",
            value: fmtInt(V.today.telegram_visitors),
            foot: <Delta cur={V.today.telegram_visitors} prev={V.yesterday.telegram_visitors} label="vs yday" />,
          },
        ]}
      />

      <div className="kit-grid-2">
        <Card title="Needs attention" sub="Things that moved, so you do not have to go looking">
          <div className="ov-attn">
            {attention.map((item) => (
              <div key={item.title} className="ov-attn-item">
                <span className={`ov-attn-icon is-${item.level}`}>{ICON[item.level]}</span>
                <div>
                  {item.title}
                  <p>{item.detail}</p>
                </div>
                <button type="button" className="kit-link" onClick={() => onGo(item.go)}>
                  Open →
                </button>
              </div>
            ))}
            {!attention.length ? <p className="kit-muted">All quiet.</p> : null}
          </div>
        </Card>
        <Card title="Strategies today" sub="Fired and hit today, with the 30-day rate for reference">
          <table className="kit-table">
            <thead>
              <tr>
                <th>Strategy</th>
                <th className="r">Fired</th>
                <th className="r">Hits</th>
                <th className="r">Today</th>
                <th className="r">30 days</th>
              </tr>
            </thead>
            <tbody>
              {body.strategies.map((row) => {
                const meta = strategies.find((s) => s.key === row.strategy);
                return (
                  <tr key={row.strategy} className="is-click" onClick={() => onGo(`results:${row.strategy}`)}>
                    <td>
                      <span className="kit-tag">{short(row.strategy)}</span>
                      {meta && !meta.enabled ? <small>disabled</small> : null}
                    </td>
                    <td className="r kit-num">{row.today.total}</td>
                    <td className="r kit-num">
                      {row.today.confirmed}/{row.today.settled}
                    </td>
                    <td className="r kit-num">{pct(row.today.hit_rate)}</td>
                    <td className="r kit-num kit-muted">{pct(row.month.hit_rate)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      </div>

      <div className="kit-grid-2 kit-grid-even">
        <Card title="Hit rate, last 14 days" sub="All strategies">
          <LineChart
            ariaLabel="Hit rate, last 14 days"
            height={200}
            baseline={fortnightSettled ? fortnightHits / fortnightSettled : null}
            points={body.hit_daily.map((d) => ({
              label: fmtShort(d.date),
              title: fmtDay(d.date),
              value: d.hit_rate,
              rows: [
                ["Hit rate", pct(d.hit_rate)],
                ["Hits / settled", `${d.confirmed} / ${d.settled}`],
              ],
            }))}
          />
        </Card>
        <Card
          title="Visitors, last 14 days"
          right={
            <Legend
              items={[
                { label: "New", color: "var(--s1)" },
                { label: "Returning", color: "var(--s2)" },
              ]}
            />
          }
        >
          <StackedBars
            ariaLabel="Visitors, last 14 days"
            height={200}
            columns={body.visitor_daily.map((d, i) => ({
              label: fmtShort(d.date),
              title: fmtDay(d.date),
              a: d.new,
              b: d.returning,
              dim: i === body.visitor_daily.length - 1,
              rows: [
                ["Visitors", fmtInt(d.new + d.returning)],
                ["New", fmtInt(d.new)],
                ["Returning", fmtInt(d.returning)],
              ],
            }))}
          />
        </Card>
      </div>
    </>
  );
}
