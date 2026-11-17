import { useEffect, useState, useRef } from "react";
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  Building2,
  ChevronRight,
  CircleHelp,
  Database,
  ExternalLink,
  Globe2,
  LayoutDashboard,
  Layers3,
  LoaderCircle,
  Plus,
  RefreshCw,
  PanelLeftClose,
  PanelLeftOpen,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  X,
} from "lucide-react";
import {
  ResponsiveContainer,
  LineChart,
  AreaChart,
  Area,
  Line,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
  BarChart,
  Bar,
  Cell,
  ReferenceLine,
  Legend,
} from "recharts";
import CompanyBrowser from "./CompanyBrowser.jsx";
import { request, startJob } from "../lib/api.js";

const money = (value) =>
  value == null
    ? "—"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        notation: "compact",
        maximumFractionDigits: 1,
      }).format(value);
const pct = (value) =>
  value == null ? "—" : `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`;
const day = (value) => {
  if (!value) return "Unavailable";
  const timestamp = value.includes("T");
  return new Date(
    timestamp ? value : value.slice(0, 10) + "T12:00:00Z",
  ).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: timestamp ? "America/New_York" : "UTC",
  });
};
const colors = ["#79a8ff", "#a293ec", "#60c6ac", "#eeb779"];
const chartStyle = { fontFamily: "system-ui", fontSize: 13 };

function ChartTip({ active, payload, label, percent = false }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="chart-tooltip">
      <strong>{label}</strong>
      {payload.map((item, i) => (
        <div key={i}>
          <span style={{ color: item.color }}>{item.name}</span>
          <b>
            {percent ? `${Number(item.value).toFixed(1)}%` : money(item.value)}
          </b>
        </div>
      ))}
      {payload[0]?.payload?.end && (
        <small>Year ended {day(payload[0].payload.end)}</small>
      )}
    </div>
  );
}
function EmptyChart() {
  return (
    <div className="empty-chart">
      <Activity size={28} />
      <p>Annual financial data isn’t available yet.</p>
      <small>Use Refresh data to retrieve the public sources.</small>
    </div>
  );
}
const numericTone = (value) =>
  !Number.isFinite(value) || value === 0
    ? "data-neutral"
    : value > 0
      ? "data-positive"
      : "data-negative";
const toneColor = (value) =>
  !Number.isFinite(value) || value === 0
    ? "var(--data-neutral)"
    : value > 0
      ? "var(--data-positive)"
      : "var(--data-negative)";
const trendChange = (series) => {
  const points = (series || []).map((p) => p.value).filter(Number.isFinite);
  return points.length > 1 ? points.at(-1) - points[0] : null;
};
function Metric({ label, value, detail, series, toneValue }) {
  return (
    <article className="metric-tile">
      <span>{label}</span>
      <div className={`metric-value ${numericTone(toneValue)}`}>{value}</div>
      <div className="metric-bottom">
        <small>{detail}</small>
        {series?.length > 1 && (
          <div className="mini-trend" aria-hidden="true">
            <ResponsiveContainer width="100%" height={36}>
              <LineChart data={series}>
                <Line
                  dataKey="value"
                  stroke={toneColor(trendChange(series))}
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </article>
  );
}

export default function ResearchDashboard({
  disabled,
  mutationDisabled = disabled,
  inventoryVersion,
  backgroundDownload,
  downloadStatus,
  sourceError,
  onDismissSourceError,
  research,
  library,
  settings,
  onPrompt,
  onCompanyChange,
  onDataBusy,
}) {
  const [catalog, setCatalog] = useState([]),
    [active, setActive] = useState(""),
    [profiles, setProfiles] = useState({}),
    [loading, setLoading] = useState(true),
    [error, setError] = useState("");
  const [view, setView] = useState("overview"),
    [comparison, setComparison] = useState([]),
    [metric, setMetric] = useState("revenue");
  const [refreshing, setRefreshing] = useState(false),
    [sidebarOpen, setSidebarOpen] = useState(false),
    [range, setRange] = useState("all");
  const [browsing, setBrowsing] = useState(false);
  const initialSelection = useRef(false);
  const sidebarRef = useRef(null);
  useEffect(() => {
    const pane = sidebarRef.current;
    if (!sidebarOpen || !pane) return;
    const containWheel = (event) => {
      if (!event.deltaY || event.shiftKey) return;
      let node =
        event.target instanceof Element
          ? event.target
          : event.target.parentElement;
      while (node && node !== pane.parentElement) {
        const scrollable =
          node === pane || /auto|scroll/.test(getComputedStyle(node).overflowY);
        if (scrollable && node.scrollHeight > node.clientHeight) {
          const canScroll =
            event.deltaY < 0
              ? node.scrollTop > 0
              : node.scrollTop + node.clientHeight < node.scrollHeight - 1;
          if (canScroll) return;
        }
        node = node.parentElement;
      }
      event.preventDefault();
    };
    pane.addEventListener("wheel", containWheel, { passive: false });
    return () => pane.removeEventListener("wheel", containWheel);
  }, [sidebarOpen]);

  const comparisonKey = comparison.join(",");
  useEffect(() => {
    const abort = new AbortController();
    setLoading(true);
    setError("");
    Promise.all([
      request("/research/catalog", { signal: abort.signal }),
      ...Array.from(new Set([active, ...comparison]))
        .filter(Boolean)
        .map((t) =>
          request(`/research/companies/${t}`, { signal: abort.signal }),
        ),
    ])
      .then(([list, ...data]) => {
        setCatalog(list.companies);
        if (!list.companies.length) setActive("");
        if (
          list.companies.length &&
          (!initialSelection.current ||
            !list.companies.some((c) => c.ticker === active))
        ) {
          if (!initialSelection.current)
            setComparison(list.companies.slice(0, 2).map((c) => c.ticker));
          initialSelection.current = true;
          setActive(
            (list.companies.find((c) => c.tracked) || list.companies[0]).ticker,
          );
        }
        setProfiles((previous) => ({
          ...previous,
          ...Object.fromEntries(data.map((p) => [p.ticker, p])),
        }));
      })
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      })
      .finally(() => {
        if (!abort.signal.aborted) setLoading(false);
      });
    return () => abort.abort();
  }, [active, comparisonKey, inventoryVersion]);
  useEffect(() => {
    if (view === "compare") onCompanyChange(comparison);
    else if (view === "overview") onCompanyChange(active ? [active] : []);
  }, [active, view, comparisonKey, onCompanyChange]);
  useEffect(() => {
    if (!sidebarOpen) return;
    const close = (e) => {
      if (e.key === "Escape") {
        setSidebarOpen(false);
      }
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [sidebarOpen]);
  useEffect(() => {
    if (backgroundDownload) setSidebarOpen(false);
  }, [backgroundDownload]);
  const company = profiles[active] ||
    catalog.find((c) => c.ticker === active) || {
      ticker: active,
      name: active,
    };
  const fullHistory = company.history || [];
  const history =
      range === "all" ? fullHistory : fullHistory.slice(-Number(range)),
    metrics = company.metrics || {};
  const selectedTrendColor = toneColor(
    trendChange(history.map((p) => ({ value: p[metric] }))),
  );
  const tracked = catalog.filter((c) => c.tracked);
  useEffect(() => {
    const abort = new AbortController();
    const missing = catalog.filter((c) => c.tracked && !profiles[c.ticker]);
    if (missing.length)
      Promise.all(
        missing.map((c) =>
          request(`/research/companies/${c.ticker}`, { signal: abort.signal }),
        ),
      )
        .then((data) =>
          setProfiles((p) => ({
            ...p,
            ...Object.fromEntries(data.map((c) => [c.ticker, c])),
          })),
        )
        .catch((e) => {
          if (e.name !== "AbortError") setError(e.message);
        });
    return () => abort.abort();
  }, [catalog]);
  async function refresh() {
    if (mutationDisabled) return;
    setRefreshing(true);
    onDataBusy(true);
    setError("");
    try {
      const targets = view === "compare" ? comparison : [active];
      const data = await Promise.all(
        targets.map((ticker) =>
          request(`/research/companies/${ticker}?refresh=true`),
        ),
      );
      setProfiles((p) => ({
        ...p,
        ...Object.fromEntries(data.map((company) => [company.ticker, company])),
      }));
    } catch (e) {
      setError(e.message);
    } finally {
      setRefreshing(false);
      onDataBusy(false);
    }
  }
  function prompt(text) {
    onPrompt(text);
    if (view !== "overview" && view !== "compare") setView("research");
    setTimeout(() => {
      document
        .getElementById("question")
        ?.scrollIntoView?.({ behavior: "smooth", block: "center" });
      document.getElementById("question")?.focus();
    }, 0);
  }
  const period = metrics.period_end
    ? `Year ended ${day(metrics.period_end)}`
    : "Annual financials";
  const compareData = Array.from(
    new Set(
      comparison.flatMap((t) =>
        (profiles[t]?.history || []).map((p) => p.year),
      ),
    ),
  )
    .sort()
    .map((year) => ({
      year,
      ...Object.fromEntries(
        comparison.map((t) => [
          t,
          profiles[t]?.history?.find((p) => p.year === year)?.revenue ?? null,
        ]),
      ),
    }));
  const prompts = [
    `Explain how ${company.name} (${active}) generates revenue.`,
    `Summarize ${active}'s latest annual performance and profit margin.`,
    `What risks should I research further for ${active}?`,
  ];
  const nav = [
    ["overview", "Company facts", Activity],
    ["compare", "Compare companies", Layers3],
  ];
  return (
    <div
      className={`atlas-dashboard ${sidebarOpen ? "pane-open" : "pane-collapsed"}`}
    >
      <button
        className="pane-toggle"
        aria-label={sidebarOpen ? "Collapse sidebar" : "Expand sidebar"}
        aria-expanded={sidebarOpen}
        onClick={() => setSidebarOpen(!sidebarOpen)}
      >
        {sidebarOpen ? (
          <PanelLeftClose size={21} />
        ) : (
          <PanelLeftOpen size={21} />
        )}
      </button>
      <aside
        ref={sidebarRef}
        className="dashboard-sidebar"
        aria-label="Company controls"
      >
        <div
          className="pane-content"
          inert={!sidebarOpen}
          aria-hidden={!sidebarOpen}
        >
          <div className="dashboard-brand">
            <img src="/capgemini-icon.png" alt="Capgemini" />
            <div>
              <h1>Corporate Atlas</h1>
              <small>COMPANY INTELLIGENCE</small>
            </div>
          </div>
          <div className="sidebar-section-label">EXPLORE</div>
          <nav>
            {nav.map(([key, label, Icon]) => (
              <button
                className={view === key ? "active" : ""}
                disabled={disabled}
                key={key}
                onClick={() => {
                  setView(key);
                  setSidebarOpen(false);
                }}
              >
                <Icon size={17} />
                {label}
                {view === key && <ChevronRight size={14} />}
              </button>
            ))}
          </nav>
          <div className="pane-settings">{settings}</div>
          <button
            className="sidebar-add"
            disabled={mutationDisabled || refreshing}
            onClick={refresh}
          >
            <RefreshCw size={15} className={refreshing ? "spin" : ""} />
            {refreshing ? "Refreshing…" : "Refresh data"}
          </button>
          <div className="pane-library">{library}</div>
          <div className="sidebar-bottom">
            <div className="connected-source">
              <span />
              Public data sources
            </div>
            <p>Company profiles & financial disclosures</p>
            <a
              href="https://www.mediawiki.org/wiki/Wikimedia_REST_API"
              target="_blank"
              rel="noreferrer"
            >
              <CircleHelp size={14} />
              About data sources
              <ExternalLink size={11} />
            </a>
          </div>
        </div>
      </aside>
      {sourceError && (
        <div className="integration-backdrop">
          <section
            className="integration-modal"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="source-unavailable-title"
          >
            <h2 id="source-unavailable-title">Check the ticker</h2>
            <p>{sourceError.message}</p>
            <p>Not available in the checked sources:</p>
            <ul>
              {sourceError.sources.map((source) => (
                <li key={source}>{source}</li>
              ))}
            </ul>
            <button className="primary" onClick={onDismissSourceError}>
              Close
            </button>
          </section>
        </div>
      )}
      <div className="dashboard-main">
        <div className="dashboard-content">
          <header className="company-strip" aria-label="Tracked companies">
            {tracked.map((c) => (
              <button
                key={c.ticker}
                disabled={disabled}
                aria-label={`Select ${c.ticker}`}
                aria-pressed={active === c.ticker && view === "overview"}
                onClick={() => {
                  setActive(c.ticker);
                  setView("overview");
                }}
                className={
                  active === c.ticker && view === "overview" ? "active" : ""
                }
              >
                <b>{c.ticker}</b>
              </button>
            ))}
            <button
              className="browse-all-trigger"
              aria-expanded={browsing}
              onClick={() => setBrowsing(!browsing)}
            >
              <Plus size={14} />
              Browse all
            </button>
          </header>
          {downloadStatus}
          {browsing && (
            <CompanyBrowser
              companies={catalog}
              active={active}
              disabled={disabled}
              mutationDisabled={mutationDisabled}
              onOpen={(ticker) => {
                setActive(ticker);
                setView("overview");
              }}
              onClose={() => setBrowsing(false)}
            />
          )}
          {error && (
            <div className="error banner" role="alert">
              {error}
            </div>
          )}
          {!loading && !catalog.length && (
            <section className="dashboard-card">
              <h2>No companies indexed yet</h2>
              <p>
                Download a ticker in the left pane. Companies appear here after
                their available content is stored in Chroma.
              </p>
            </section>
          )}
          <div className="company-analysis-flow">
            <div
              className="insight-main"
              key={view === "compare" ? "comparison" : active}
            >
              {active && (view === "overview" || view === "compare") && (
                <>
                  {loading && !profiles[active] && (
                    <div className="research-loading" role="status">
                      <LoaderCircle className="spin" size={20} />
                      Loading company research…
                    </div>
                  )}
                  {view === "overview" ? (
                    <>
                      <section className="company-heading">
                        <div>
                          <h3>
                            {company.name}
                            <span>{active}</span>
                          </h3>
                          <p>
                            {company.profile?.description ||
                              company.sector ||
                              "Public company"}
                          </p>
                        </div>
                        <span className="sector-badge">{company.sector}</span>
                      </section>
                      <div className="metric-grid">
                        <Metric
                          label="Annual revenue"
                          value={money(metrics.revenue)}
                          detail={period}
                          series={history.map((p) => ({ value: p.revenue }))}
                        />
                        <Metric
                          label="Net income"
                          toneValue={metrics.net_income}
                          value={money(metrics.net_income)}
                          detail={period}
                          series={history.map((p) => ({ value: p.net_income }))}
                        />
                        <Metric
                          label="Revenue growth"
                          toneValue={metrics.revenue_growth}
                          value={pct(metrics.revenue_growth)}
                          detail="vs. previous annual period"
                          series={[]}
                        />
                        <Metric
                          label="Net profit margin"
                          toneValue={metrics.net_margin}
                          value={
                            metrics.net_margin == null
                              ? "—"
                              : `${metrics.net_margin.toFixed(1)}%`
                          }
                          detail="Net income ÷ revenue"
                          series={history.map((p) => ({ value: p.net_margin }))}
                        />
                      </div>
                      <div className="overview-chart-grid">
                        <section
                          className="dashboard-card trend-card"
                          id="annual-financial-trend"
                        >
                          <div className="card-top">
                            <div>
                              <h3>Financial performance</h3>
                              <p>Annual results · USD billions</p>
                            </div>
                            <div className="segmented-control">
                              {[
                                ["revenue", "Revenue"],
                                ["net_income", "Net income"],
                              ].map(([key, label]) => (
                                <button
                                  key={key}
                                  disabled={disabled}
                                  className={metric === key ? "active" : ""}
                                  onClick={() => setMetric(key)}
                                >
                                  {label}
                                </button>
                              ))}
                            </div>
                          </div>
                          <div
                            className="chart-range"
                            role="group"
                            aria-label="Financial history range"
                          >
                            {[
                              ["3", "3Y"],
                              ["5", "5Y"],
                              ["all", "All"],
                            ].map(([key, label]) => (
                              <button
                                key={key}
                                disabled={disabled}
                                aria-pressed={range === key}
                                className={range === key ? "active" : ""}
                                onClick={() => setRange(key)}
                              >
                                {label}
                              </button>
                            ))}
                            <span>
                              {history.length} annual periods · fiscal year end
                            </span>
                          </div>
                          {history.length ? (
                            <>
                              <div
                                className="financial-chart"
                                style={{ "--trend-color": selectedTrendColor }}
                                aria-label={`Annual ${metric === "revenue" ? "revenue" : "net income"} chart for ${active}`}
                              >
                                <ResponsiveContainer width="100%" height={260}>
                                  <AreaChart
                                    data={history}
                                    margin={{
                                      top: 15,
                                      right: 15,
                                      left: 0,
                                      bottom: 5,
                                    }}
                                  >
                                    <defs>
                                      <linearGradient
                                        id="annual-fill"
                                        x1="0"
                                        y1="0"
                                        x2="0"
                                        y2="1"
                                      >
                                        <stop
                                          offset="0%"
                                          stopColor={selectedTrendColor}
                                          stopOpacity={0.25}
                                        />
                                        <stop
                                          offset="100%"
                                          stopColor={selectedTrendColor}
                                          stopOpacity={0.01}
                                        />
                                      </linearGradient>
                                    </defs>
                                    <CartesianGrid
                                      stroke="#293342"
                                      strokeDasharray="3 5"
                                      vertical={false}
                                    />
                                    <XAxis
                                      dataKey="year"
                                      tick={chartStyle}
                                      stroke="#acbad0"
                                      tickLine={false}
                                      axisLine={false}
                                    />
                                    <YAxis
                                      tick={chartStyle}
                                      stroke="#acbad0"
                                      tickLine={false}
                                      axisLine={false}
                                      width={48}
                                      tickFormatter={(v) =>
                                        `$${(v / 1e9).toFixed(0)}B`
                                      }
                                      domain={[
                                        (min) => Math.min(0, min),
                                        "auto",
                                      ]}
                                    />
                                    <Tooltip content={<ChartTip />} />
                                    <Area
                                      type="monotone"
                                      dataKey={metric}
                                      name={
                                        metric === "revenue"
                                          ? "Revenue"
                                          : "Net income"
                                      }
                                      stroke={selectedTrendColor}
                                      fill="url(#annual-fill)"
                                      strokeWidth={2.5}
                                      dot={{
                                        r: 3,
                                        fill: selectedTrendColor,
                                        strokeWidth: 0,
                                      }}
                                      activeDot={{ r: 5 }}
                                      connectNulls={false}
                                    />
                                  </AreaChart>
                                </ResponsiveContainer>
                              </div>
                              <div className="chart-footer">
                                <span>Source: SEC company facts</span>
                                <a
                                  href={company.financial_source}
                                  target="_blank"
                                  rel="noreferrer"
                                >
                                  View source
                                  <ExternalLink size={11} />
                                </a>
                              </div>
                            </>
                          ) : (
                            <EmptyChart />
                          )}
                        </section>
                        <section className="dashboard-card profile-card">
                          <div className="card-top">
                            <h3>About {company.name}</h3>
                            <Globe2 size={17} />
                          </div>
                          <p className="company-description">
                            {company.profile?.summary ||
                              "No public company overview is saved yet. Refresh data to retrieve one."}
                          </p>
                          <div className="profile-tags">
                            <span>{company.sector}</span>
                            <span>Public company</span>
                          </div>
                          {company.profile && (
                            <a
                              className="profile-link"
                              href={company.profile.source_url}
                              target="_blank"
                              rel="noreferrer"
                            >
                              Read company profile
                              <ArrowUpRight size={14} />
                            </a>
                          )}
                          <small className="profile-license">
                            Wikipedia text · CC BY-SA. See source article for
                            attribution.
                          </small>
                        </section>
                      </div>
                      <div className="insights-grid">
                        <section
                          className="dashboard-card margin-card"
                          id="annual-net-margin"
                        >
                          <div className="card-top">
                            <div>
                              <h3>Profitability over time</h3>
                              <p>Net income as a share of annual revenue</p>
                            </div>
                            <Activity size={17} />
                          </div>
                          {history.some((p) => p.net_margin != null) ? (
                            <div className="margin-chart">
                              <ResponsiveContainer width="100%" height={195}>
                                <BarChart
                                  data={history}
                                  margin={{
                                    top: 10,
                                    right: 10,
                                    left: 0,
                                    bottom: 0,
                                  }}
                                >
                                  <CartesianGrid
                                    stroke="#293342"
                                    strokeDasharray="3 5"
                                    vertical={false}
                                  />
                                  <XAxis
                                    dataKey="year"
                                    tick={chartStyle}
                                    tickLine={false}
                                    axisLine={false}
                                    stroke="#acbad0"
                                  />
                                  <YAxis
                                    tick={chartStyle}
                                    tickLine={false}
                                    axisLine={false}
                                    stroke="#acbad0"
                                    width={42}
                                    tickFormatter={(v) => `${v}%`}
                                  />
                                  <ReferenceLine y={0} stroke="#738096" />
                                  <Tooltip content={<ChartTip percent />} />
                                  <Bar
                                    dataKey="net_margin"
                                    name="Net margin"
                                    fill="#a49ade"
                                    maxBarSize={28}
                                    radius={[3, 3, 0, 0]}
                                  >
                                    {history.map((row) => (
                                      <Cell
                                        key={row.end}
                                        fill={toneColor(row.net_margin)}
                                      />
                                    ))}
                                  </Bar>
                                </BarChart>
                              </ResponsiveContainer>
                            </div>
                          ) : (
                            <EmptyChart />
                          )}
                          <p className="chart-definition">
                            Net profit margin = net income ÷ revenue × 100.
                            Annual periods only.
                          </p>
                        </section>
                        <section className="dashboard-card insights-card">
                          <div className="card-top">
                            <h3>Research starting points</h3>
                            <span className="insight-label">
                              <Sparkles size={12} />
                              From reported data
                            </span>
                          </div>
                          {metrics.revenue_growth != null && (
                            <div
                              className={`data-insight ${numericTone(metrics.revenue_growth)}`}
                            >
                              <span className="insight-icon">
                                {metrics.revenue_growth >= 0 ? (
                                  <ArrowUpRight size={18} />
                                ) : (
                                  <ArrowDownRight size={18} />
                                )}
                              </span>
                              <div>
                                <strong>
                                  {metrics.revenue_growth >= 0
                                    ? "Revenue expanded"
                                    : "Revenue contracted"}{" "}
                                  {Math.abs(metrics.revenue_growth).toFixed(1)}%
                                </strong>
                                <p>
                                  Latest annual period versus the previous year.
                                  Compare the full filing before drawing
                                  conclusions.
                                </p>
                              </div>
                            </div>
                          )}
                          <div className="quick-research">
                            <small>EXPLORE WITH THE ASSISTANT</small>
                            {prompts.map((text) => (
                              <button
                                key={text}
                                disabled={disabled}
                                onClick={() => prompt(text)}
                              >
                                {text}
                                <ArrowUpRight size={14} />
                              </button>
                            ))}
                          </div>
                        </section>
                      </div>
                      <div className="snapshot-footer">
                        <span>
                          <Database size={12} />
                          Snapshot retrieved {day(company.fetched_at)} ·
                          Financial period ended {day(metrics.period_end)}
                        </span>
                        <button
                          disabled={disabled}
                          className="text-button"
                          onClick={() => {
                            setSidebarOpen(true);
                          }}
                        >
                          Manage indexed filings
                          <ChevronRight size={12} />
                        </button>
                      </div>
                      {company.warnings?.map((w) => (
                        <p className="notice" key={w}>
                          {w}
                        </p>
                      ))}
                      <details className="research-source-details">
                        <summary>Sources & exact financial values</summary>
                        <p>
                          Annual financials are historical SEC-reported facts,
                          not live prices. General descriptions come from
                          Wikimedia. Reporting calendars differ across
                          companies.
                        </p>
                        <div className="source-links">
                          {company.profile && (
                            <a
                              href={company.profile.source_url}
                              target="_blank"
                              rel="noreferrer"
                            >
                              Wikimedia profile ·{" "}
                              {day(
                                company.profile_fetched_at ||
                                  company.fetched_at,
                              )}
                            </a>
                          )}
                          {company.financial_source && (
                            <a
                              href={company.financial_source}
                              target="_blank"
                              rel="noreferrer"
                            >
                              SEC XBRL facts ·{" "}
                              {day(
                                company.financial_fetched_at ||
                                  company.fetched_at,
                              )}
                            </a>
                          )}
                        </div>
                        <div className="table-scroll">
                          <table>
                            <thead>
                              <tr>
                                <th>Period end</th>
                                <th>Revenue (USD)</th>
                                <th>Net income (USD)</th>
                                <th>Net margin</th>
                              </tr>
                            </thead>
                            <tbody>
                              {history.map((row) => (
                                <tr key={row.end}>
                                  <td>{row.end}</td>
                                  <td>{row.revenue?.toLocaleString()}</td>
                                  <td className={numericTone(row.net_income)}>
                                    {row.net_income?.toLocaleString() ??
                                      "Unavailable"}
                                  </td>
                                  <td className={numericTone(row.net_margin)}>
                                    {row.net_margin == null
                                      ? "Unavailable"
                                      : `${row.net_margin.toFixed(2)}%`}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </details>
                    </>
                  ) : (
                    <>
                      <div className="comparison-picker">
                        {tracked.map((c) => (
                          <label key={c.ticker}>
                            <input
                              type="checkbox"
                              disabled={
                                disabled ||
                                (!comparison.includes(c.ticker) &&
                                  comparison.length >= 4) ||
                                (comparison.includes(c.ticker) &&
                                  comparison.length === 1)
                              }
                              checked={comparison.includes(c.ticker)}
                              onChange={(e) =>
                                setComparison(
                                  e.target.checked
                                    ? [...comparison, c.ticker]
                                    : comparison.filter((t) => t !== c.ticker),
                                )
                              }
                            />
                            {c.name}
                            <span>{c.ticker}</span>
                          </label>
                        ))}
                      </div>
                      <section className="dashboard-card comparison-chart">
                        <div className="card-top">
                          <div>
                            <h3>Annual revenue comparison</h3>
                            <p>
                              USD billions · aligned by year-end calendar year
                            </p>
                          </div>
                        </div>
                        <ResponsiveContainer width="100%" height={310}>
                          <LineChart data={compareData}>
                            <CartesianGrid
                              stroke="#293342"
                              strokeDasharray="3 5"
                              vertical={false}
                            />
                            <XAxis
                              dataKey="year"
                              stroke="#acbad0"
                              tick={chartStyle}
                            />
                            <YAxis
                              tickFormatter={(v) => `$${(v / 1e9).toFixed(0)}B`}
                              stroke="#acbad0"
                              tick={chartStyle}
                              width={64}
                              domain={[0, "auto"]}
                            />
                            <Tooltip content={<ChartTip />} />
                            <Legend />
                            {comparison.map((t, i) => (
                              <Line
                                key={t}
                                dataKey={t}
                                name={t}
                                stroke={colors[i]}
                                strokeWidth={2.5}
                                dot={{ r: 2 }}
                                connectNulls={false}
                              />
                            ))}
                          </LineChart>
                        </ResponsiveContainer>
                        <p className="chart-definition">
                          Fiscal year ends differ; annual periods are not
                          identical. Missing observations are left blank.
                        </p>
                      </section>
                      <section className="dashboard-card comparison-table">
                        <h3>Latest annual snapshot</h3>
                        <div className="table-scroll">
                          <table>
                            <thead>
                              <tr>
                                <th>Company</th>
                                <th>Period end</th>
                                <th>Revenue</th>
                                <th>Net income</th>
                                <th>Revenue growth</th>
                                <th>Net margin</th>
                              </tr>
                            </thead>
                            <tbody>
                              {comparison.map((t) => {
                                const p = profiles[t],
                                  m = p?.metrics || {};
                                return (
                                  <tr key={t}>
                                    <td>
                                      {p?.name || t} · {t}
                                    </td>
                                    <td>{day(m.period_end)}</td>
                                    <td>{money(m.revenue)}</td>
                                    <td className={numericTone(m.net_income)}>
                                      {money(m.net_income)}
                                    </td>
                                    <td
                                      className={numericTone(m.revenue_growth)}
                                    >
                                      {pct(m.revenue_growth)}
                                    </td>
                                    <td className={numericTone(m.net_margin)}>
                                      {m.net_margin == null
                                        ? "—"
                                        : `${m.net_margin.toFixed(1)}%`}
                                    </td>
                                  </tr>
                                );
                              })}
                            </tbody>
                          </table>
                        </div>
                        <button
                          disabled={disabled}
                          className="secondary"
                          onClick={() =>
                            prompt(
                              `Compare ${comparison.join(" and ")} using their annual revenue growth, profit margins, and reporting periods.`,
                            )
                          }
                        >
                          <Sparkles size={14} />
                          Explore this comparison
                        </button>
                      </section>
                    </>
                  )}
                </>
              )}
            </div>
            {
              <section
                className={`research-assistant-section ${view === "overview" || view === "compare" ? "compact-assistant" : ""}`}
              >
                {research}
              </section>
            }
          </div>
          <footer className="dashboard-footer">
            <span>Corporate Atlas · Evidence, in perspective.</span>
            <span>Wikimedia + SEC EDGAR</span>
          </footer>
        </div>
      </div>
    </div>
  );
}
