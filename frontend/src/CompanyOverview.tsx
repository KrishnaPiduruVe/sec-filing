import { useEffect, useState } from "react";
import { getCompanyLabel, getCompanyOverview } from "./api";
import { getWikipediaProfile } from "./wikipedia";
import type { AnnualFinancialPeriod, Company, CompanyOverviewData } from "./types";

function percent(value: number | null | undefined, signed = false): string {
  if (value == null) return "—";
  const formatted = new Intl.NumberFormat(undefined, {
    style: "percent",
    signDisplay: signed ? "exceptZero" : "auto",
    maximumFractionDigits: 1,
  });
  return formatted.format(value / 100);
}

function periodEnd(date: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeZone: "UTC",
  }).format(new Date(date));
}

function Profitability({ periods }: { periods: AnnualFinancialPeriod[] }) {
  const reported = periods.flatMap(({ period_end, net_margin }) =>
    net_margin == null ? [] : [{ end: period_end, margin: net_margin }],
  );
  if (!reported.length) return <p>Annual profit margins are unavailable.</p>;

  const min = Math.min(0, ...reported.map(({ margin }) => margin));
  const max = Math.max(0, ...reported.map(({ margin }) => margin));
  const span = max - min || 1;
  const baseline = (max / span) * 100;

  return (
    <div className="profitability-chart" role="img" aria-label={
      reported.map(({ end, margin }) => `Year ended ${periodEnd(end)}: ${percent(margin)} net margin`).join("; ")
    }>
      <div className="profitability-plot">
        <div className="profitability-baseline" style={{ top: `${baseline}%` }} />
      </div>
      {reported.map(({ end, margin }) => (
        <div className="profitability-year" key={end} aria-hidden="true">
          <div className="profitability-bar-track" title={`Year ended ${periodEnd(end)} · ${percent(margin)}`}>
            <div className={`profitability-bar ${margin < 0 ? "loss" : ""}`}
              style={{ top: `${((max - Math.max(margin, 0)) / span) * 100}%`, height: `${(Math.abs(margin) / span) * 100}%` }} />
          </div>
          <span className="profitability-value">{percent(margin)}</span>
          <span>{end.slice(0, 4)}</span>
        </div>
      ))}
    </div>
  );
}

type Props = {
  company: Company;
  sector?: string | null;
  industry?: string | null;
  businessSummary?: string | null;
  onPrompt: (question: string) => void;
  formatMoney: (value: number | null | undefined, currency: string, compact?: boolean) => string;
};

export function CompanyOverview({ company, sector, industry, businessSummary, onPrompt, formatMoney }: Props) {
  const [overview, setOverview] = useState<CompanyOverviewData>();
  const [failed, setFailed] = useState(false);
  const [wikiProfile, setWikiProfile] = useState<CompanyOverviewData["profile"]>();
  const [wikiDone, setWikiDone] = useState(false);
  const { name, ticker } = company;
  useEffect(() => {
    const controller = new AbortController();
    void getCompanyOverview(ticker, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setOverview(data);
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => controller.abort();
  }, [ticker]);

  const overviewReady = Boolean(overview) || failed;
  const savedProfile = overview?.profile;
  useEffect(() => {
    if (!overviewReady || savedProfile) return;
    const controller = new AbortController();
    async function findProfile() {
      try {
        const label = await getCompanyLabel(ticker, controller.signal).catch(() => null);
        if (controller.signal.aborted) return;
        const registrant = label?.label.endsWith(` (${ticker})`) ? label.label.slice(0, -(ticker.length + 3)) : name;
        const result = await getWikipediaProfile(registrant, controller.signal);
        if (!controller.signal.aborted) setWikiProfile(result);
      } catch {
        // Use the market-data profile if Wikipedia is unavailable.
      } finally {
        if (!controller.signal.aborted) setWikiDone(true);
      }
    }
    void findProfile();
    return () => controller.abort();
  }, [name, overviewReady, savedProfile, ticker]);

  const periods = overview?.financials?.periods ?? [];
  const latest = periods.at(-1);
  const growth = overview?.financials?.revenue_growth;
  const end = latest ? `Year ended ${periodEnd(latest.period_end)}` : "Annual figures unavailable";
  const profile = savedProfile ?? wikiProfile;
  const profileText = profile?.text || businessSummary;
  const profileLoading = !profile && !wikiDone;
  const tags = [...new Set([sector, industry].filter(Boolean))];
  const prompts = [
    `How does ${name} ($${ticker}) generate revenue?`,
    `What do the saved filings say about $${ticker}'s profitability and its main drivers?`,
    `What risks should I research further for $${ticker}?`,
  ];

  return (
    <section className="company-overview" aria-label="Company research overview">
      <div className="overview-heading">
        <h2>Annual financials</h2>
        {overview?.financials && <a href={overview.financials.source} target="_blank" rel="noreferrer">SEC Company Facts ↗</a>}
      </div>
      {!overview && !failed ? <p className="overview-status" role="status">Loading company information…</p> : (
        <div className="annual-metrics">
          {[
            { label: "Annual revenue", value: latest ? formatMoney(latest.revenue, latest.currency, true) : "—", note: end },
            { label: "Net income", value: latest ? formatMoney(latest.net_income, latest.currency, true) : "—", note: end, sign: latest?.net_income },
            { label: "Revenue growth", value: percent(growth, true), note: "Versus the previous fiscal year", sign: growth },
            { label: "Net profit margin", value: percent(latest?.net_margin), note: "Net income ÷ revenue", sign: latest?.net_margin },
          ].map(({ label, value, note, sign }) => (
            <div className="overview-card annual-metric" key={label}>
              <span>{label}</span>
              <strong className={sign == null || sign === 0 ? "" : sign > 0 ? "positive" : "negative"}>{value}</strong>
              <small>{note}</small>
            </div>
          ))}
        </div>
      )}

      <section className="overview-card company-profile">
        <h2>About {name}</h2>
        {profileText ? <p>{profileText}</p> : (
          <p role="status">{profileLoading ? "Looking up the company on Wikipedia…" : "A matching Wikipedia company profile is unavailable."}</p>
        )}
        {tags.length > 0 && <ul className="profile-tags">{tags.map((tag) => <li key={tag}>{tag}</li>)}</ul>}
        {profile ? (
          <>
            <a href={profile.source} target="_blank" rel="noreferrer">Read on Wikipedia ↗</a>
            <small>Wikipedia contributors · <a href="https://creativecommons.org/licenses/by-sa/4.0/" target="_blank" rel="noreferrer">CC BY-SA 4.0</a></small>
          </>
        ) : businessSummary ? <small>Source: Yahoo Finance</small> : null}
      </section>

      <div className="overview-pair">
        <section className="overview-card">
          <h2>Profitability over time</h2>
          {overview || failed ? <Profitability periods={periods} /> : <p>Loading annual profit margins…</p>}
          <small>Net income as a share of annual revenue</small>
        </section>
        <section className="overview-card">
          <h2>Research starting points</h2>
          {growth != null && (
            <p className="research-observation">
              Revenue {growth === 0 ? "was unchanged" : growth > 0 ? `grew ${percent(growth)}` : `fell ${percent(-growth)}`} versus the previous fiscal year.
            </p>
          )}
          <div className="research-prompts">
            {prompts.map((prompt) => (
              <button key={prompt} type="button" onClick={() => onPrompt(prompt)}>{prompt} <span aria-hidden="true">↗</span></button>
            ))}
          </div>
        </section>
      </div>
    </section>
  );
}
