import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { askQuestion, askUsageQuestion, cancelJob, getClientConfig, indexStock, listCompanies, prepareSec, stockSnapshot, waitForJob } from "./api";
import Chart from "./Chart";
import { AssistantResponse } from "./AssistantResponse";
import type { ChatMessage, ClientConfig, Company, Job, StockSnapshot } from "./types";
import capgeminiMark from "../../src/ui/corporate_atlas_ui/assets/capgemini-icon.png";

type Theme = "light" | "dark";

function formatJobConsole(section: string, job: Job): string {
  const steps = Object.entries(job.steps ?? {})
    .filter(([, step]) => step.status !== "pending")
    .map(([name, step]) => `${name}: ${step.status}${step.message ? ` — ${step.message}` : ""}`);
  const progress = steps.length ? `${steps.join("\n")}\n\n` : "";
  return `[${section}]\n${progress}${job.output.trim() || "Waiting for worker output…"}`;
}

function money(value: number | null | undefined, currency: string, compact = false): string {
  if (value == null || !Number.isFinite(value)) return "—";
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency,
      notation: compact ? "compact" : "standard",
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${currency} ${new Intl.NumberFormat(undefined, { notation: compact ? "compact" : "standard", maximumFractionDigits: 2 }).format(value)}`;
  }
}

function number(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 2 }).format(value);
}

function shortTime(value: number | null | undefined): string {
  if (!value) return "Market data";
  return `As of ${new Date(value * 1000).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}`;
}

function safeWebsite(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

function makeMessage(
  role: ChatMessage["role"],
  content: string,
  scope: ChatMessage["scope"],
): ChatMessage {
  return { id: `${Date.now()}-${Math.random()}`, role, content, scope };
}

function isTokenUsageQuestion(value: string): boolean {
  return /\bhow\s+(?:much|many)\s+(?:input\s+|output\s+)?tokens?\b|\b(?:input|output)\s+tokens?\b|\btoken\s+(?:usage|consumption|count|total)\b|\btokens?\s+(?:used|consumed|spent)\b/i.test(value);
}

function shouldRouteToUsage(prompt: string, messages: ChatMessage[]): boolean {
  if (isTokenUsageQuestion(prompt)) return true;
  const previousUserQuestion = messages.filter((message) => message.role === "user").at(-1);
  return Boolean(
    previousUserQuestion
    && isTokenUsageQuestion(previousUserQuestion.content)
    && /\b(?:sql|sqlite|database|this|that|it|those|same|break\s+down|by\s+(?:model|operation|date|month))\b/i.test(prompt),
  );
}

function initials(name: string): string {
  return name.split(/\s+/).slice(0, 2).map((part) => part[0] ?? "").join("").toUpperCase();
}

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="stat">
      <span className="stat-label">{label}</span>
      <strong>{value}</strong>
      {note && <span className="stat-note">{note}</span>}
    </div>
  );
}

export default function App() {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [clientConfig, setClientConfig] = useState<ClientConfig | null>(null);
  const [configError, setConfigError] = useState("");
  const [selected, setSelected] = useState("");
  const [search, setSearch] = useState("");
  const [tickerInput, setTickerInput] = useState("");
  const [range, setRange] = useState("");
  const [snapshot, setSnapshot] = useState<StockSnapshot | null>(null);
  const [snapshotLoading, setSnapshotLoading] = useState(false);
  const [snapshotError, setSnapshotError] = useState("");
  const [listError, setListError] = useState("");
  const [adding, setAdding] = useState(false);
  const [addStatus, setAddStatus] = useState("");
  const [addError, setAddError] = useState("");
  const [addCancelled, setAddCancelled] = useState(false);
  const [activeJobId, setActiveJobId] = useState("");
  const [stopPending, setStopPending] = useState(false);
  const [jobConsole, setJobConsole] = useState("");
  const [consoleExpanded, setConsoleExpanded] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [queryScope, setQueryScope] = useState<"research" | "usage">("research");
  const [chatBusy, setChatBusy] = useState(false);
  const [chatError, setChatError] = useState("");
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [theme, setTheme] = useState<Theme>(() => {
    const savedTheme = window.localStorage.getItem("atlas-theme");
    if (savedTheme === "light" || savedTheme === "dark") return savedTheme;
    return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  });
  const searchInputRef = useRef<HTMLInputElement>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const cancelRequestedRef = useRef(false);

  const refreshCompanies = useCallback(async (preferred?: string) => {
    try {
      const { companies: rows } = await listCompanies();
      setCompanies(rows);
      setListError("");
      setSelected((current) => {
        const choice = preferred || current || window.localStorage.getItem("atlas-selected-ticker") || "";
        return rows.some((company) => company.ticker === choice)
          ? choice
          : rows[0]?.ticker ?? "";
      });
    } catch (error) {
      setListError(error instanceof Error ? error.message : "Unable to load saved companies.");
    }
  }, []);

  useEffect(() => {
    void refreshCompanies();
  }, [refreshCompanies]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("atlas-theme", theme);
  }, [theme]);

  useEffect(() => {
    getClientConfig()
      .then((config) => {
        setClientConfig(config);
        setRange((current) =>
          config.frontend.stock_chart_ranges.includes(current)
            ? current
            : config.frontend.stock_chart_ranges[0],
        );
        setConfigError("");
      })
      .catch((error: unknown) => {
        setConfigError(
          error instanceof Error ? error.message : "Unable to load application settings.",
        );
      });
  }, []);

  useEffect(() => {
    if (!selected || !range) {
      setSnapshot(null);
      return;
    }
    window.localStorage.setItem("atlas-selected-ticker", selected);
    const controller = new AbortController();
    setSnapshotLoading(true);
    setSnapshotError("");
    stockSnapshot(selected, range, controller.signal)
      .then(setSnapshot)
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setSnapshotError(error instanceof Error ? error.message : "Unable to load stock details.");
          setSnapshot(null);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setSnapshotLoading(false);
      });
    return () => controller.abort();
  }, [selected, range]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, chatBusy]);

  useEffect(() => {
    function focusCompanySearch(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchInputRef.current?.focus();
      }
    }
    window.addEventListener("keydown", focusCompanySearch);
    return () => window.removeEventListener("keydown", focusCompanySearch);
  }, []);

  const filteredCompanies = useMemo(() => {
    const term = search.trim().toLowerCase();
    return companies.filter((company) => !term
      || company.ticker.toLowerCase().includes(term)
      || company.name.toLowerCase().includes(term));
  }, [companies, search]);

  const currentCompany = companies.find((company) => company.ticker === selected);
  const quote = snapshot?.quote;
  const displayCompanyName = quote?.name && quote.name.toUpperCase() !== selected
    ? quote.name
    : currentCompany?.name;
  const currentPrice = quote?.current_price;
  const previousClose = quote?.previous_close;
  const priceChange = currentPrice != null && previousClose != null ? currentPrice - previousClose : null;
  const percentChange = priceChange != null && previousClose ? (priceChange / previousClose) * 100 : null;
  const isPositive = (priceChange ?? 0) >= 0;
  const defaultCurrency = clientConfig?.market_data.default_currency ?? "";
  const companyWebsite = safeWebsite(quote?.website);

  async function addCompany(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const ticker = tickerInput.trim().toUpperCase();
    if (!ticker || !clientConfig) return;
    setAdding(true);
    setAddError("");
    setAddCancelled(false);
    setActiveJobId("");
    setStopPending(false);
    cancelRequestedRef.current = false;
    setAddStatus("Preparing SEC filings and research indexes…");
    setConsoleExpanded(false);
    setJobConsole("[SEC filing preparation]\nStarting worker…");
    try {
      const filingJob = await prepareSec(
        ticker,
        clientConfig.indexing.batch_size,
        clientConfig.indexing.batch_delay_seconds,
      );
      setActiveJobId(filingJob.id);
      const filingResult = await waitForJob(filingJob, (_output, latest) => {
        setJobConsole(formatJobConsole("SEC filing preparation", latest));
      }, clientConfig.frontend.job_poll_interval_ms);
      setActiveJobId("");
      if (cancelRequestedRef.current) throw new Error("Task stopped by user.");
      setAddStatus("Fetching current market data and adding it to search…");
      const stockLogPrefix = `${formatJobConsole("SEC filing preparation", filingResult)}\n\n`;
      setJobConsole(`${stockLogPrefix}[Stock data indexing]\nStarting worker…`);
      const stockJob = await indexStock(ticker);
      setActiveJobId(stockJob.id);
      const stockResult = await waitForJob(stockJob, (_output, latest) => {
        setJobConsole(`${stockLogPrefix}${formatJobConsole("Stock data indexing", latest)}`);
      }, clientConfig.frontend.job_poll_interval_ms);
      setActiveJobId("");
      if (cancelRequestedRef.current) throw new Error("Task stopped by user.");
      setJobConsole(`${stockLogPrefix}${formatJobConsole("Stock data indexing", stockResult)}`);
      setTickerInput("");
      await refreshCompanies(ticker);
      setAddStatus(`${ticker} is ready for research.`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unable to add this company.";
      if (cancelRequestedRef.current) {
        setAddCancelled(true);
        setAddStatus("Task stopped.");
        setAddError("");
        setJobConsole((output) => `${output.trimEnd()}\n\n[Task stopped by user.]`);
      } else {
        setAddError(message);
        setAddStatus("");
        setJobConsole((output) => `${output.trimEnd()}\n\n[Task failed: ${message}]`);
      }
    } finally {
      setActiveJobId("");
      setStopPending(false);
      setAdding(false);
    }
  }

  async function stopAddJob() {
    if (!activeJobId || stopPending) return;
    cancelRequestedRef.current = true;
    setStopPending(true);
    setAddError("");
    setAddStatus("Stopping current task…");
    try {
      await cancelJob(activeJobId);
    } catch (error) {
      cancelRequestedRef.current = false;
      setStopPending(false);
      setAddError(error instanceof Error ? error.message : "Unable to stop the current task.");
    }
  }

  async function submitQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const prompt = question.trim();
    if (!prompt || chatBusy || !clientConfig) return;
    const autoRouteToUsage = queryScope === "research" && shouldRouteToUsage(prompt, messages);
    const requestScope = autoRouteToUsage ? "usage" : queryScope;
    const relevantMessages = autoRouteToUsage
      ? messages.filter((message) => message.role === "user" && isTokenUsageQuestion(message.content))
      : messages.filter((message) => message.scope === requestScope);
    const history = relevantMessages
      .slice(-clientConfig.query.max_history_messages)
      .map(({ role, content }) => ({
        role,
        content: content.slice(0, clientConfig.query.max_history_message_chars),
      }));
    setQuestion("");
    setChatError("");
    if (autoRouteToUsage) setQueryScope("usage");
    setMessages((items) => {
      const withUsageHistory = autoRouteToUsage
        ? items.map((message) => (
          message.role === "user" && isTokenUsageQuestion(message.content)
            ? { ...message, scope: "usage" as const }
            : message
        ))
        : items;
      return [...withUsageHistory, makeMessage("user", prompt, requestScope)];
    });
    setChatBusy(true);
    try {
      const job = requestScope === "usage"
        ? await askUsageQuestion(prompt, clientConfig.query.top_k, history)
        : await askQuestion(prompt, clientConfig.query.top_k, history);
      const completed = await waitForJob(
        job,
        () => undefined,
        clientConfig.frontend.job_poll_interval_ms,
      );
      setMessages((items) => [...items, makeMessage("assistant", completed.output.trim() || "No answer was returned.", requestScope)]);
    } catch (error) {
      setChatError(error instanceof Error ? error.message : "The question could not be answered.");
    } finally {
      setChatBusy(false);
    }
  }

  function useSuggestion(value: string) {
    setQuestion(value);
    document.getElementById("chat-question")?.focus();
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="/" aria-label="Corporate Atlas home">
          <img className="brand-mark" src={capgeminiMark} alt="Capgemini" />
          <span className="brand-copy">
            <strong>Corporate Atlas</strong>
            <small>Company intelligence</small>
          </span>
        </a>

        <div className="sidebar-label">YOUR RESEARCH</div>
        {configError && <p className="sidebar-error" role="alert">{configError}</p>}
        <label className="search-box">
          <span aria-hidden="true">⌕</span>
          <input
            type="search"
            ref={searchInputRef}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Find a company"
            aria-label="Filter available companies"
          />
          <kbd>⌘ K</kbd>
        </label>

        <div className="company-list" aria-label="Available companies">
          {listError && <p className="sidebar-error">{listError}</p>}
          {filteredCompanies.map((company) => (
            <button
              className={`company-item ${selected === company.ticker ? "selected" : ""}`}
              key={company.ticker}
              onClick={() => {
                setSelected(company.ticker);
                setMessages([]);
                setDetailsOpen(false);
              }}
            >
              <span className={`company-avatar avatar-${company.ticker.charCodeAt(0) % 5}`}>{initials(company.name)}</span>
              <span className="company-copy">
                <strong>{company.name}</strong>
                <small>{company.ticker}{company.exchange ? ` · ${company.exchange}` : ""}</small>
              </span>
              <span className="company-chevron" aria-hidden="true">›</span>
            </button>
          ))}
          {!filteredCompanies.length && (
            <div className="empty-companies">
              <span className="empty-icon">⌕</span>
              {companies.length ? "No companies match your search." : "Your research list is empty. Add a company below to get started."}
            </div>
          )}
        </div>

        <div className="sidebar-add">
          <div className="add-title">
            <span className="add-icon">＋</span>
            <div><strong>Add company</strong><small>Prepare SEC filing research</small></div>
          </div>
          <form onSubmit={addCompany}>
            <label htmlFor="ticker-input">Ticker symbol</label>
            <div className="ticker-input-wrap">
              <input
                id="ticker-input"
                value={tickerInput}
                onChange={(event) => setTickerInput(event.target.value)}
                placeholder="e.g. NVDA"
                maxLength={15}
                disabled={adding}
                autoCapitalize="characters"
                autoComplete="off"
              />
              <button
                className={adding ? "add-stop-button" : ""}
                type={adding ? "button" : "submit"}
                onClick={adding ? () => void stopAddJob() : undefined}
                disabled={adding ? !activeJobId || stopPending : !clientConfig || !tickerInput.trim()}
                aria-label={adding ? "Stop current task" : "Add company"}
                title={adding ? (stopPending ? "Stopping task" : "Stop indexing") : "Add company"}
              >
                {adding ? (
                  <>
                    <span className="spinner small" aria-hidden="true" />
                    <span className="stop-symbol" aria-hidden="true">■</span>
                  </>
                ) : "→"}
              </button>
            </div>
          </form>
          {adding && <div className="add-status"><span className="spinner small" />{addStatus}</div>}
          {!adding && addStatus && <div className={addCancelled ? "add-cancelled" : "add-success"}>{addStatus}</div>}
          {addError && <div className="add-error" role="alert">{addError}</div>}
          {(adding || jobConsole) && (
            <button
              className="console-toggle"
              type="button"
              onClick={() => setConsoleExpanded((expanded) => !expanded)}
              aria-expanded={consoleExpanded}
              aria-controls={consoleExpanded ? "job-console" : undefined}
            >
              {consoleExpanded ? "Hide logs" : "Show logs"}
              <span aria-hidden="true">{consoleExpanded ? "⌄" : "›"}</span>
            </button>
          )}
          <p>Downloads filings and indexes current stock information.</p>
        </div>

        <div className="sidebar-footer">
          <span className="status-dot" />
          <span>Private workspace</span>
          <span className="footer-spacer" />
          <span className="footer-version">LOCAL</span>
        </div>
      </aside>

      <main className="main-panel">
        <header className="topbar">
          <div className="breadcrumb"><span>Research</span><span className="crumb-slash">/</span><strong>{selected || "Overview"}</strong></div>
          <div className="topbar-actions">
            <div className="topbar-note"><span className="shield-icon">◆</span> Grounded in your saved research</div>
            <button
              className="theme-toggle"
              type="button"
              onClick={() => setTheme((current) => current === "dark" ? "light" : "dark")}
              aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
              title={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
            >
              <span aria-hidden="true">{theme === "dark" ? "☀" : "☾"}</span>
              <span>{theme === "dark" ? "Light" : "Dark"}</span>
            </button>
          </div>
        </header>

        <div className="content-scroll">
          {consoleExpanded && jobConsole && (
            <section className="job-console" id="job-console" aria-label="Job console output">
              <div className="console-header">
                <span className="console-heading">
                  <strong>Console output</strong>
                  <small>{adding ? addStatus : "Most recent company indexing job"}</small>
                </span>
                <span className={`console-state ${adding ? "running" : addError ? "failed" : "complete"}`}>
                  {adding ? "RUNNING" : addError ? "FAILED" : addCancelled ? "STOPPED" : "COMPLETE"}
                </span>
                <button type="button" onClick={() => setConsoleExpanded(false)} aria-label="Hide console output">×</button>
              </div>
              <pre aria-live="polite">{jobConsole || "Waiting for worker output…"}</pre>
            </section>
          )}
          {!currentCompany ? (
            <section className="welcome-panel">
              <div className="welcome-kicker"><span className="status-dot" /> YOUR RESEARCH WORKSPACE</div>
              <h1>Research companies<br />with more context.</h1>
              <p>Prepare SEC filings, explore market performance, and ask questions across your saved research in one place.</p>
              <div className="welcome-steps">
                <div><span>01</span><strong>Add a ticker</strong><small>Download filings and market data</small></div>
                <div><span>02</span><strong>Explore the company</strong><small>Review charts and key information</small></div>
                <div><span>03</span><strong>Ask a question</strong><small>Get answers grounded in your index</small></div>
              </div>
              {companies.length > 0 && <button className="primary-button" onClick={() => setSelected(companies[0].ticker)}>Open {companies[0].ticker}</button>}
            </section>
          ) : (
            <div className="company-page">
              <section className="company-heading">
                <div className={`company-avatar heading-avatar avatar-${currentCompany.ticker.charCodeAt(0) % 5}`}>{initials(currentCompany.name)}</div>
                <div className="heading-copy">
                  <div className="eyebrow">{currentCompany.ticker}{currentCompany.exchange ? ` · ${currentCompany.exchange}` : ""}</div>
                  <h1>{displayCompanyName || currentCompany.name}</h1>
                  <p>{quote?.sector || "Company profile"}{quote?.industry ? ` · ${quote.industry}` : ""}</p>
                </div>
                <button className="refresh-button" onClick={() => void refreshCompanies(selected)} title="Refresh saved companies">
                  <span aria-hidden="true">↻</span><span>Refresh list</span>
                </button>
              </section>

              <section className="market-card" aria-label="Stock market overview">
                <div className="market-topline">
                  <div>
                    <div className="section-eyebrow">MARKET OVERVIEW <span className="live-dot" /> {quote?.market_state || "LATEST DATA"}</div>
                    {snapshotLoading && <div className="loading-inline"><span className="spinner small" />Updating market data…</div>}
                    {snapshotError && <div className="inline-error" role="alert">{snapshotError}</div>}
                    {quote && (
                      <div className="price-line">
                        <strong>{money(currentPrice, quote.currency || defaultCurrency)}</strong>
                        {priceChange != null && (
                          <span className={`price-change ${isPositive ? "positive" : "negative"}`}>
                            <span>{isPositive ? "↗" : "↘"}</span>
                            {money(Math.abs(priceChange), quote.currency || defaultCurrency)} ({percentChange?.toFixed(2)}%)
                          </span>
                        )}
                      </div>
                    )}
                    <div className="market-subline">
                      {quote
                        ? `${shortTime(quote.quote_time)} · ${quote.quote_source === "alpaca" ? "Alpaca IEX" : "Yahoo Finance"}`
                        : "Live quote and price history"}
                    </div>
                    {quote?.quote_source === "yahoo_fallback" && (
                      <div className="market-fallback-note">
                        Alpaca is unavailable; displaying Yahoo Finance backup data.
                      </div>
                    )}
                    {quote?.quote_source === "chart_fallback" && (
                      <div className="market-fallback-note">
                        Yahoo quote details are rate-limited; showing available chart data. Some metrics are unavailable.
                      </div>
                    )}
                    {quote?.quote_source === "alpaca" && (
                      <div className="market-fallback-note">
                        {quote.fundamentals_source === "yahoo"
                          ? "Prices use Alpaca IEX; company fundamentals are supplemented by Yahoo Finance."
                          : "Prices use Alpaca IEX. Yahoo Finance fundamentals are unavailable, so some company metrics may be missing."}
                      </div>
                    )}
                  </div>
                  <div className="range-tabs" role="group" aria-label="Chart range">
                    {(clientConfig?.frontend.stock_chart_ranges ?? []).map((item) => (
                      <button className={range === item ? "active" : ""} key={item} onClick={() => setRange(item)}>
                        {item.toUpperCase()}
                      </button>
                    ))}
                  </div>
                </div>

                {snapshotLoading && !snapshot ? (
                  <div className="chart-skeleton"><span className="spinner" />Loading price history</div>
                ) : snapshot ? (
                  <Chart points={snapshot.chart} currency={quote?.currency || defaultCurrency} />
                ) : (
                  <div className="chart-empty">Stock information is not available yet. Try refreshing the company list or add the ticker again.</div>
                )}

                {quote && (
                  <div className="market-stats">
                    <Stat label="Market cap" value={money(quote.market_cap, quote.currency || defaultCurrency, true)} />
                    <Stat label="52-week high" value={money(quote.fifty_two_week_high, quote.currency || defaultCurrency)} />
                    <Stat label="52-week low" value={money(quote.fifty_two_week_low, quote.currency || defaultCurrency)} />
                    <Stat label="Day range" value={quote.day_range || "—"} note="Today" />
                    <Stat label="Volume" value={number(quote.volume)} />
                    <Stat label="Average volume" value={number(quote.average_volume)} />
                  </div>
                )}
              </section>

              <button
                className={`details-toggle ${detailsOpen ? "open" : ""}`}
                onClick={() => setDetailsOpen((open) => !open)}
                aria-expanded={detailsOpen}
              >
                <span className="details-toggle-icon">▤</span>
                <span><strong>Company details</strong><small>Valuation, profile, and trading information</small></span>
                <span className="details-chevron">{detailsOpen ? "⌃" : "⌄"}</span>
              </button>
              {detailsOpen && quote && (
                <section className="details-panel">
                  <div className="details-grid">
                    <Stat label="Previous close" value={money(quote.previous_close, quote.currency || defaultCurrency)} />
                    <Stat label="Open" value={money(quote.open, quote.currency || defaultCurrency)} />
                    <Stat label="P/E ratio" value={quote.trailing_pe?.toFixed(2) ?? "—"} />
                    <Stat label="Beta" value={quote.beta?.toFixed(2) ?? "—"} />
                    <Stat label="Dividend yield" value={quote.dividend_yield == null ? "—" : `${(quote.dividend_yield * 100).toFixed(2)}%`} />
                    <Stat label="Price to book" value={quote.price_to_book?.toFixed(2) ?? "—"} />
                  </div>
                  {quote.long_business_summary && <p className="business-summary">{quote.long_business_summary}</p>}
                  {companyWebsite && <a className="website-link" href={companyWebsite} target="_blank" rel="noreferrer">{companyWebsite} <span>↗</span></a>}
                  <p className="market-disclaimer">Market information is provided for research purposes and may be delayed. Verify current figures with your broker or data provider.</p>
                </section>
              )}

              <section className="chat-card">
                <div className="chat-header">
                  <div className="chat-heading-icon">✳</div>
                  <div className="chat-heading-copy">
                    <h2>{queryScope === "usage" ? "Ask about token usage" : "Ask your research"}</h2>
                    <p>{queryScope === "usage" ? "Answers use metrics from your local SQLite database." : "Answers are grounded in saved SEC filings and stock information."}</p>
                  </div>
                  <select
                    className="chat-scope"
                    aria-label="Question scope"
                    value={queryScope}
                    onChange={(event) => setQueryScope(event.target.value === "usage" ? "usage" : "research")}
                  >
                    <option value="research">SEC + stock</option>
                    <option value="usage">Token usage</option>
                  </select>
                  <span className="chat-context">{queryScope === "usage" ? "Local SQLite" : `${companies.length} indexed`}</span>
                  <button
                    className="new-chat-button"
                    type="button"
                    onClick={() => {
                      setMessages([]);
                      setQuestion("");
                      setChatError("");
                    }}
                    disabled={chatBusy || (!messages.length && !question)}
                  >
                    + New chat
                  </button>
                </div>

                <div className="chat-body" aria-live="polite">
                  {!messages.length ? (
                    <div className="chat-welcome">
                      <div className="assistant-avatar">✳</div>
                      <div className="chat-intro">
                        <strong>{queryScope === "usage" ? "What usage metrics do you need?" : "What would you like to understand?"}</strong>
                        <p>{queryScope === "usage"
                          ? "Ask about input/output tokens, estimated events, models, or usage by operation."
                          : `Ask about ${currentCompany.name}, compare companies, or explore a filing detail.`}</p>
                        <div className="suggestions">
                          {queryScope === "usage" ? (
                            <>
                              <button onClick={() => useSuggestion("Summarize input and output tokens by operation for the last 30 days.")}>Tokens by operation</button>
                              <button onClick={() => useSuggestion("How many usage events were estimated versus provider-reported?")}>Estimated events</button>
                            </>
                          ) : (
                            <>
                              <button onClick={() => useSuggestion(`What are the key risks reported by ${currentCompany.name}?`)}>What are the key risks?</button>
                              <button onClick={() => useSuggestion(`Summarize the recent financial trends for ${currentCompany.name}.`)}>Summarize financial trends</button>
                            </>
                          )}
                        </div>
                      </div>
                    </div>
                  ) : messages.map((message) => (
                    <div className={`chat-message ${message.role}`} key={message.id}>
                      {message.role === "assistant" && <div className="assistant-avatar">✳</div>}
                      <div className="message-bubble">
                        <span className="message-label">{message.role === "assistant" ? "ATLAS" : "YOU"}</span>
                        {message.role === "assistant" ? (
                          <div className="message-content">
                            <AssistantResponse content={message.content} />
                          </div>
                        ) : (
                          <p>{message.content}</p>
                        )}
                      </div>
                    </div>
                  ))}
                  {chatBusy && (
                    <div className="chat-message assistant">
                      <div className="assistant-avatar">✳</div>
                      <div className="message-bubble"><span className="message-label">ATLAS</span><div className="typing-indicator"><i /><i /><i /> {queryScope === "usage" ? "Querying local usage metrics" : "Searching saved context"}</div></div>
                    </div>
                  )}
                  {chatError && <div className="chat-error" role="alert">{chatError}</div>}
                  <div ref={chatEndRef} />
                </div>

                <form className="chat-form" onSubmit={submitQuestion}>
                  <label className="sr-only" htmlFor="chat-question">{queryScope === "usage" ? "Ask about token usage" : "Ask about saved research"}</label>
                  <textarea
                    id="chat-question"
                    rows={1}
                    maxLength={clientConfig?.query.max_question_chars}
                    value={question}
                    onChange={(event) => setQuestion(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && !event.shiftKey) {
                        event.preventDefault();
                        event.currentTarget.form?.requestSubmit();
                      }
                    }}
                    placeholder={queryScope === "usage" ? "Ask about token usage…" : "Ask a question about your research…"}
                    disabled={chatBusy || !clientConfig}
                  />
                  <button type="submit" disabled={chatBusy || !clientConfig || !question.trim()} aria-label="Send question">↑</button>
                  <div className="chat-footnote"><span>Enter to send · Shift + Enter for a new line</span><span>{queryScope === "usage" ? "SQLite usage metrics" : "SEC + stock context"}</span></div>
                </form>
              </section>
              <footer className="page-footer">Corporate Atlas · Research workspace <span>Market data may be delayed.</span></footer>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
