"use client";

import type { ReactNode } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type Holding = {
  ticker: string;
  invested: number;
  value: number;
  return_pct: number;
  allocation_pct: number;
};

type Analysis = {
  start_date: string;
  end_date: string;
  invested: number;
  value: number;
  return_pct: number;
  holdings: Holding[];
  history: { date: string; value: number; holdings: Record<string, number> }[];
};

type Insight = { title: string; description: string; sentiment: "bullish" | "bearish" };

/** Shared agent state, as emitted by the backend in STATE_SNAPSHOT events. */
export type PortfolioState = {
  request?: { positions: Record<string, number>; start_date: string };
  analysis?: Analysis;
  insights?: Insight[];
};

const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const usdCompact = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  notation: "compact",
});
// Dates arrive as YYYY-MM-DD, which Date parses as UTC; format in UTC to keep the same day.
const day = new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeZone: "UTC" });
const month = new Intl.DateTimeFormat("en-US", { month: "short", year: "2-digit", timeZone: "UTC" });
const formatDay = (iso: string) => day.format(new Date(iso));

// The arrow and sign carry the direction, so gain and loss never depend on color alone.
const signedPct = (pct: number) => `${pct >= 0 ? "▲ +" : "▼ −"}${Math.abs(pct).toFixed(2)}%`;
const signedUsd = (amount: number) => `${amount >= 0 ? "+" : "−"}${usd.format(Math.abs(amount))}`;
const tone = (amount: number) => (amount >= 0 ? "text-up" : "text-down");

const axisTick = { fill: "var(--ink-dim)", fontSize: 11 };

export function Panel({
  title,
  titleClassName = "text-accent",
  className = "",
  children,
}: {
  title: string;
  titleClassName?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section aria-label={title} className={`border border-rule bg-panel ${className}`}>
      <h2 className={`h-9 border-b border-rule px-3 text-xs leading-9 font-semibold tracking-widest uppercase ${titleClassName}`}>
        {title}
      </h2>
      {children}
    </section>
  );
}

function Summary({ analysis }: { analysis: Analysis }) {
  const gain = analysis.value - analysis.invested;
  const rows: [string, string, string][] = [
    ["Invested", usd.format(analysis.invested), "text-cyan"],
    ["Value", usd.format(analysis.value), "text-ink"],
    ["P/L", signedUsd(gain), tone(gain)],
    ["Return", signedPct(analysis.return_pct), tone(gain)],
    ["Since", formatDay(analysis.start_date), "text-ink"],
    ["As of", formatDay(analysis.end_date), "text-ink"],
    ["Holdings", String(analysis.holdings.length), "text-cyan"],
  ];
  return (
    <dl className="px-3 py-2 text-xs tabular-nums">
      {rows.map(([label, value, className]) => (
        <div key={label} className="flex justify-between gap-4 py-1.5">
          <dt className="tracking-wider text-ink-dim uppercase">{label}</dt>
          <dd className={`font-semibold ${className}`}>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function ValueChart({ analysis }: { analysis: Analysis }) {
  return (
    <div
      role="img"
      aria-label={`Portfolio value went from ${usd.format(analysis.invested)} on ${formatDay(analysis.start_date)} to ${usd.format(analysis.value)} on ${formatDay(analysis.end_date)}.`}
      className="h-72 p-2"
    >
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={analysis.history} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--rule)" />
          <XAxis
            dataKey="date"
            tickFormatter={(iso: string) => month.format(new Date(iso))}
            minTickGap={48}
            tickLine={false}
            axisLine={{ stroke: "var(--rule)" }}
            tick={axisTick}
          />
          <YAxis
            orientation="right"
            domain={["auto", "auto"]}
            tickFormatter={(value: number) => usdCompact.format(value)}
            width={56}
            tickLine={false}
            axisLine={false}
            tick={axisTick}
          />
          <Tooltip
            formatter={(value) => [usd.format(Number(value)), "Value"]}
            labelFormatter={(iso) => formatDay(String(iso))}
            cursor={{ stroke: "var(--ink-dim)" }}
            contentStyle={{
              background: "var(--surface)",
              border: "1px solid var(--rule)",
              borderRadius: 0,
              fontSize: 12,
            }}
            labelStyle={{ color: "var(--ink-dim)" }}
            itemStyle={{ color: "var(--ink)" }}
          />
          <ReferenceLine
            y={analysis.invested}
            ifOverflow="extendDomain"
            stroke="var(--accent)"
            strokeDasharray="4 4"
          />
          <Line
            dataKey="value"
            stroke="var(--series)"
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function Sparkline({ values }: { values: number[] }) {
  const low = Math.min(...values);
  const range = Math.max(...values) - low || 1;
  const points = values
    .map((value, i) => `${(i / (values.length - 1)) * 100},${30 - ((value - low) / range) * 28}`)
    .join(" ");
  return (
    <svg viewBox="0 0 100 32" preserveAspectRatio="none" aria-hidden="true" className="h-8 w-20">
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

function Movers({ analysis }: { analysis: Analysis }) {
  const ranked = [...analysis.holdings].sort((a, b) => b.return_pct - a.return_pct);
  return (
    <ul className="grid grid-cols-[repeat(auto-fill,minmax(12rem,1fr))] gap-0.5 p-0.5 tabular-nums">
      {ranked.map((holding) => (
        <li
          key={holding.ticker}
          className={`px-3 py-2 text-white ${holding.return_pct >= 0 ? "bg-tile-up" : "bg-tile-down"}`}
        >
          <p className="text-xs">{holding.ticker}</p>
          <div className="flex items-center justify-between gap-2">
            <p className="text-lg font-semibold whitespace-nowrap">{signedPct(holding.return_pct)}</p>
            <Sparkline values={analysis.history.map((point) => point.holdings[holding.ticker])} />
          </div>
          <p className="flex justify-between gap-2 text-xs">
            <span>{usd.format(holding.value)}</span>
            <span>{signedUsd(holding.value - holding.invested)}</span>
          </p>
        </li>
      ))}
    </ul>
  );
}

function Holdings({ holdings }: { holdings: Holding[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[36rem] text-xs tabular-nums">
        <thead>
          <tr className="border-b border-rule text-left tracking-wider text-ink-dim uppercase">
            <th scope="col" className="px-3 py-2 font-medium">Stock</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">Invested</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">Value</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">Return</th>
            <th scope="col" className="px-3 py-2 font-medium">Share of portfolio</th>
          </tr>
        </thead>
        <tbody>
          {holdings.map((holding) => (
            <tr key={holding.ticker} className="border-b border-rule last:border-b-0">
              <th scope="row" className="px-3 py-2 text-left font-semibold text-accent">{holding.ticker}</th>
              <td className="px-3 py-2 text-right text-cyan">{usd.format(holding.invested)}</td>
              <td className="px-3 py-2 text-right">{usd.format(holding.value)}</td>
              <td className={`px-3 py-2 text-right ${tone(holding.return_pct)}`}>
                {signedPct(holding.return_pct)}
              </td>
              <td className="px-3 py-2">
                <div className="flex items-center gap-3">
                  <div className="h-2 flex-1">
                    <div className="h-2 bg-series" style={{ width: `${holding.allocation_pct}%` }} />
                  </div>
                  <span className="w-12 text-right">{holding.allocation_pct.toFixed(1)}%</span>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function InsightPanel({
  title,
  titleClassName,
  insights,
  running,
}: {
  title: string;
  titleClassName: string;
  insights?: Insight[];
  running: boolean;
}) {
  return (
    <Panel title={title} titleClassName={titleClassName}>
      <div className="px-3 py-2 text-xs" aria-live="polite">
        {insights?.length ? (
          <ul className="space-y-3">
            {insights.map((insight) => (
              <li key={insight.title}>
                <p className="font-semibold">{insight.title}</p>
                <p className="mt-1 max-w-prose leading-relaxed text-ink-dim">{insight.description}</p>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-ink-dim">{running ? "Writing insights…" : "None for this analysis."}</p>
        )}
      </div>
    </Panel>
  );
}

export function Portfolio({ state, running }: { state: PortfolioState; running: boolean }) {
  const { request, analysis, insights } = state ?? {};

  if (!analysis) {
    return (
      <Panel title="Portfolio">
        <p className="max-w-prose px-3 py-3 text-xs leading-relaxed text-ink-dim" aria-live="polite">
          {running && request
            ? `Analyzing ${Object.keys(request.positions).join(", ")} since ${formatDay(request.start_date)}…`
            : "No portfolio loaded. Ask in the chat, for example: “Analyze AAPL and MSFT with $10k each since January 2024.” The value over time, each holding and the agent’s insights appear here as it works."}
        </p>
      </Panel>
    );
  }

  const gain = analysis.value - analysis.invested;
  return (
    <div className="grid gap-2 xl:grid-cols-[16rem_minmax(0,1fr)]">
      <h1 className="flex flex-wrap items-baseline gap-x-6 gap-y-1 border border-rule bg-panel px-3 py-2 tabular-nums xl:col-span-2">
        <span className="text-xs font-semibold tracking-widest text-accent uppercase">Portfolio</span>
        <span className="text-2xl font-semibold">{usd.format(analysis.value)}</span>
        <span className={`text-sm ${tone(gain)}`}>{signedUsd(gain)}</span>
        <span className={`text-sm ${tone(gain)}`}>{signedPct(analysis.return_pct)}</span>
      </h1>

      <Panel title="Summary">
        <Summary analysis={analysis} />
      </Panel>
      <Panel title="Value over time" className="min-w-0">
        {/* Keyed here rather than on the plot, where the label would collide with the line. */}
        <p className="px-3 pt-2 text-xs text-ink-dim">
          <span aria-hidden="true" className="text-accent">╌╌ </span>
          Invested {usd.format(analysis.invested)}
        </p>
        <ValueChart analysis={analysis} />
      </Panel>

      <Panel title="Movers" className="xl:col-span-2">
        <Movers analysis={analysis} />
      </Panel>
      <Panel title="Holdings" className="min-w-0 xl:col-span-2">
        <Holdings holdings={analysis.holdings} />
      </Panel>

      <div className="grid gap-2 sm:grid-cols-2 xl:col-span-2">
        <InsightPanel
          title="▲ Bullish"
          titleClassName="text-up"
          insights={insights?.filter((insight) => insight.sentiment === "bullish")}
          running={running}
        />
        <InsightPanel
          title="▼ Bearish"
          titleClassName="text-down"
          insights={insights?.filter((insight) => insight.sentiment === "bearish")}
          running={running}
        />
      </div>
    </div>
  );
}
