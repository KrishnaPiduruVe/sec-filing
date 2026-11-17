import { useEffect, useRef, useState, lazy, Suspense } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Settings,
  X,
  ArrowUpRight,
  Download,
  FileText,
  CheckCircle2,
} from "lucide-react";
import { request, startJob, isBusy, saveText } from "./lib/api.js";
import Workflow, {
  Processing,
  BackgroundDownload,
} from "./components/Workflow.jsx";
import Companies from "./components/Companies.jsx";
const ResearchDashboard = lazy(
  () => import("./components/ResearchDashboard.jsx"),
);

export default function App() {
  const [theme, setTheme] = useState(() => {
    try {
      return localStorage.getItem("atlas-color-mode") === "light"
        ? "light"
        : "dark";
    } catch {
      return "dark";
    }
  });
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("atlas-color-mode", theme);
    } catch {
      /* Storage can be disabled. */
    }
  }, [theme]);
  const [researchTickers, setResearchTickers] = useState([]);
  const [sourceError, setSourceError] = useState(null);
  const [researchDataBusy, setResearchDataBusy] = useState(false);
  const [job, setJob] = useState(null),
    [connected, setConnected] = useState(false),
    [connectionError, setConnectionError] = useState("");
  const [downloadJob, setDownloadJob] = useState(null);
  const [pending, setPending] = useState(false),
    [error, setError] = useState(""),
    [question, setQuestion] = useState(""),
    [tickers, setTickers] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false),
    [mode, setMode] = useState("vector"),
    [topK, setTopK] = useState(12),
    [batchSize, setBatchSize] = useState(5),
    [delay, setDelay] = useState(65);
  const [queryLabel, setQueryLabel] = useState("");
  const [answer, setAnswer] = useState(""),
    [toast, setToast] = useState(null),
    [completedDeletion, setCompletedDeletion] = useState(null);
  const [usage, setUsage] = useState(null),
    [usageLoading, setUsageLoading] = useState(false),
    [usageError, setUsageError] = useState("");
  const seen = useRef(new Set()),
    mounted = useRef(true),
    currentRequest = useRef(null);
  useEffect(() => {
    if (
      !downloadJob?.source_error ||
      downloadJob.status !== "failed" ||
      Date.now() - (downloadJob.finished_at || 0) * 1000 > 60000
    )
      return;
    let seen;
    try {
      seen = sessionStorage.getItem("atlas-source-error");
    } catch {}
    if (seen === downloadJob.id) return;
    setSourceError(downloadJob.source_error);
    try {
      sessionStorage.setItem("atlas-source-error", downloadJob.id);
    } catch {}
  }, [downloadJob]);
  const busy = pending || isBusy(job),
    baseLocked = pending || researchDataBusy || !connected || !!connectionError,
    locked = baseLocked || isBusy(job),
    downloadLocked =
      baseLocked ||
      isBusy(downloadJob) ||
      (isBusy(job) && job.action === "delete_filings");

  useEffect(() => {
    mounted.current = true;
    let timer;
    const abort = new AbortController();
    async function poll() {
      try {
        const data = await request("/jobs/current", { signal: abort.signal });
        if (!mounted.current) return;
        const accept = (setter, next) => {
          if (next)
            setter((previous) =>
              previous && next.started < previous.started ? previous : next,
            );
        };
        if (data.job?.action === "prepare") accept(setDownloadJob, data.job);
        else accept(setJob, data.job);
        accept(setJob, data.query_job);
        setConnected(true);
        setConnectionError("");
      } catch (e) {
        if (e.name !== "AbortError" && mounted.current) {
          setConnectionError(e.message);
          setConnected(false);
        }
      }
      if (!abort.signal.aborted) timer = setTimeout(poll, 1000);
    }
    poll();
    return () => {
      mounted.current = false;
      abort.abort();
      currentRequest.current?.abort();
      clearTimeout(timer);
    };
  }, []);
  useEffect(() => {
    function complete(job) {
      if (!job || job.status !== "completed" || seen.current.has(job.id))
        return;
      seen.current.add(job.id);
      if (job.action === "query") {
        setAnswer(job.answer ?? job.output ?? "");
        return;
      }
      if (["delete_filings", "prepare"].includes(job.action))
        setCompletedDeletion(job.id);
      const duration = job.action === "prepare" ? 10000 : 5000;
      const expires = (job.finished_at ?? 0) * 1000 + duration;
      if (expires <= Date.now()) return;
      if (job.action === "prepare") {
        Promise.all(
          (job.tickers || []).map((t) =>
            request(`/companies/${encodeURIComponent(t)}/label`)
              .then((d) => d.label)
              .catch(() => t),
          ),
        ).then((names) => {
          if (mounted.current && expires > Date.now())
            setToast({
              message: `Information for ${names.join(", ") || "your company"} is ready. Ask a question above.`,
              expires,
              remaining: expires - Date.now(),
            });
        });
      } else if (job.action === "delete_filings")
        setToast({
          message: job.output.trim(),
          expires,
          remaining: expires - Date.now(),
        });
    }
    complete(job);
    complete(downloadJob);
  }, [job, downloadJob]);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(
      () => setToast(null),
      Math.max(0, toast.expires - Date.now()),
    );
    return () => clearTimeout(timer);
  }, [toast]);
  useEffect(() => {
    if (busy || researchDataBusy) setSettingsOpen(false);
  }, [busy, researchDataBusy]);
  useEffect(() => {
    const close = (e) => {
      if (e.key === "Escape") setSettingsOpen(false);
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, []);
  async function submit(path, data) {
    if (path === "/prepare" ? downloadLocked : locked) return;
    setPending(true);
    setError("");
    setToast(null);
    const abort = new AbortController();
    currentRequest.current = abort;
    try {
      const created = await request(path, {
        method: "POST",
        body: JSON.stringify(data),
        signal: abort.signal,
      });
      if (mounted.current) {
        if (created.action === "prepare") setDownloadJob(created);
        else setJob(created);
        if (path === "/query" || path === "/research/query") {
          setAnswer("");
          setQueryLabel(
            data.company_tickers?.join(", ") || "All saved filing evidence",
          );
        }
      }
    } catch (e) {
      if (e.name !== "AbortError" && mounted.current) setError(e.message);
    } finally {
      if (mounted.current) setPending(false);
    }
  }
  async function cancelQuery() {
    try {
      await startJob(`/jobs/${job.id}/cancel`, {});
    } catch (e) {
      setError(e.message);
    }
  }
  async function loadUsage() {
    setUsageLoading(true);
    setUsageError("");
    try {
      const data = await request("/usage");
      if (mounted.current) setUsage(data.rows);
    } catch (e) {
      if (mounted.current) setUsageError(e.message);
    } finally {
      if (mounted.current) setUsageLoading(false);
    }
  }

  return (
    <Suspense
      fallback={
        <div className="dashboard-bootstrap">
          <Processing>Loading company research…</Processing>
        </div>
      }
    >
      <ResearchDashboard
        disabled={baseLocked}
        mutationDisabled={baseLocked}
        inventoryVersion={completedDeletion}
        sourceError={sourceError}
        onDismissSourceError={() => setSourceError(null)}
        backgroundDownload={isBusy(downloadJob)}
        downloadStatus={
          <>
            <BackgroundDownload job={downloadJob} />
            {toast && (
              <div className="success-toast" role="status">
                <CheckCircle2 size={19} />
                <span>{toast.message}</span>
              </div>
            )}
          </>
        }
        onPrompt={setQuestion}
        onCompanyChange={setResearchTickers}
        onDataBusy={setResearchDataBusy}
        onPrepare={(ticker) => {
          setTickers(ticker);
          submit("/prepare", {
            tickers: ticker,
            batch_size: Number(batchSize),
            batch_delay: Number(delay),
          });
        }}
        settings={
          <>
            {" "}
            <div className="settings-wrap">
              <button
                type="button"
                className="icon-button"
                aria-label="Settings"
                aria-expanded={settingsOpen}
                disabled={baseLocked}
                onClick={() => setSettingsOpen(!settingsOpen)}
              >
                <Settings size={21} />
              </button>
              <label className="theme-selector">
                Color mode
                <select
                  aria-label="Color mode"
                  value={theme}
                  onChange={(e) => setTheme(e.target.value)}
                >
                  <option value="dark">Dark</option>
                  <option value="light">Light</option>
                </select>
              </label>
              {settingsOpen && (
                <section
                  className="settings-panel"
                  aria-label="Research settings"
                >
                  <div className="section-heading">
                    <h3>Settings</h3>
                    <button
                      className="icon-button"
                      aria-label="Close settings"
                      onClick={() => setSettingsOpen(false)}
                    >
                      <X size={17} />
                    </button>
                  </div>
                  <label>
                    Answer using
                    <select
                      value={mode}
                      onChange={(e) => setMode(e.target.value)}
                    >
                      <option value="vector">Vector store</option>
                    </select>
                  </label>
                  <label>
                    Context items per source
                    <input
                      type="number"
                      min="1"
                      max="50"
                      value={topK}
                      onChange={(e) => setTopK(e.target.value)}
                    />
                  </label>
                  <details>
                    <summary>Preparation settings</summary>
                    <label>
                      Chunks per batch
                      <input
                        type="number"
                        min="1"
                        max="100"
                        value={batchSize}
                        onChange={(e) => setBatchSize(e.target.value)}
                      />
                    </label>
                    <label>
                      Pause between batches (seconds)
                      <input
                        type="number"
                        min="0"
                        max="600"
                        value={delay}
                        onChange={(e) => setDelay(e.target.value)}
                      />
                    </label>
                  </details>
                </section>
              )}
            </div>
          </>
        }
        research={
          <>
            {" "}
            {connectionError && (
              <div className="error banner" role="alert">
                {connectionError}
              </div>
            )}
            {!connected && !connectionError && (
              <Processing>Connecting to company research…</Processing>
            )}
            <section className="question-section">
              <div className="eyebrow">
                <FileText size={15} />
                COMPANY RESEARCH
              </div>
              <h2>What would you like to know?</h2>
              <p className="muted">
                Explore your selected companies with public profiles, financial
                facts, and available filing evidence.
              </p>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  submit("/research/query", {
                    question: question.trim(),
                    mode,
                    top_k: Number(topK),
                    company_tickers: researchTickers,
                  });
                }}
              >
                <label className="sr-only" htmlFor="question">
                  Your question
                </label>
                <textarea
                  id="question"
                  placeholder="What are the key risks facing Apple? How do revenue trends compare across companies?"
                  maxLength={5000}
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  disabled={locked}
                  data-gramm="false"
                  data-gramm_editor="false"
                  data-enable-grammarly="false"
                />
                <div className="question-actions">
                  <button
                    className="primary"
                    disabled={
                      locked || !question.trim() || !researchTickers.length
                    }
                    type="submit"
                  >
                    Explore insights
                    <ArrowUpRight size={17} />
                  </button>
                </div>
              </form>
            </section>
            {error && (
              <p className="error banner" role="alert">
                {error}
              </p>
            )}
            {job?.action === "query" && isBusy(job) && (
              <div className="query-progress">
                <Processing>
                  {job.status === "stopping"
                    ? "Stopping…"
                    : "Fetching filing insights…"}
                </Processing>
                <button
                  className="text-button"
                  onClick={cancelQuery}
                  disabled={job.status === "stopping"}
                >
                  Stop task
                </button>
              </div>
            )}
            {job?.action === "query" &&
              ["failed", "stopped"].includes(job.status) && (
                <div className="error banner" role="alert">
                  {job.status === "failed"
                    ? "The question could not be answered."
                    : "The question was stopped."}
                  <details>
                    <summary>View details</summary>
                    <pre>{job.output}</pre>
                  </details>
                </div>
              )}
            {answer && (
              <section className="answer-card">
                <div className="section-heading">
                  <h3>Answer</h3>
                  <button
                    className="secondary"
                    disabled={locked}
                    onClick={() => saveText(answer)}
                  >
                    <Download size={15} />
                    Save answer
                  </button>
                </div>
                {queryLabel && (
                  <p className="answer-context">
                    Research context: {queryLabel}
                  </p>
                )}
                <div className="answer-text">
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                      a: (props) => (
                        <a
                          {...props}
                          target="_blank"
                          rel="noopener noreferrer"
                        />
                      ),
                    }}
                  >
                    {answer}
                  </ReactMarkdown>
                </div>
              </section>
            )}
          </>
        }
        library={
          <>
            {" "}
            <div className="workspace-sections">
              <details className="section-disclosure">
                <summary>Add a company to your research</summary>
                <div className="disclosure-body">
                  <p className="muted">
                    Enter a ticker to download SEC filings, its Wikimedia
                    profile, and annual financial information.
                  </p>
                  <form
                    className="download-form"
                    onSubmit={(e) => {
                      e.preventDefault();
                      submit("/prepare", {
                        tickers: tickers.trim(),
                        batch_size: Number(batchSize),
                        batch_delay: Number(delay),
                      });
                    }}
                  >
                    <label>
                      Company ticker
                      <input
                        value={tickers}
                        onChange={(e) => setTickers(e.target.value)}
                        placeholder="e.g. AAPL or AAPL, WFC"
                        disabled={downloadLocked}
                        maxLength={400}
                      />
                    </label>
                    <button
                      className="secondary"
                      type="submit"
                      disabled={downloadLocked || !tickers.trim()}
                    >
                      <Download size={16} />
                      Download
                    </button>
                  </form>
                </div>
              </details>
              {downloadJob?.status === "failed" && (
                <Workflow job={downloadJob} />
              )}
              <details className="section-disclosure">
                <summary>Usage</summary>
                <div className="disclosure-body">
                  <button
                    className="secondary"
                    disabled={baseLocked || usageLoading}
                    onClick={loadUsage}
                  >
                    View token usage
                  </button>
                  {usageLoading ? (
                    <Processing>Loading token usage…</Processing>
                  ) : (
                    <>
                      {usageError && (
                        <p role="alert" className="error">
                          {usageError}
                        </p>
                      )}
                      {usage?.length > 0 && (
                        <div className="table-scroll">
                          <table>
                            <thead>
                              <tr>
                                {[
                                  "Operation",
                                  "Input tokens",
                                  "Output tokens",
                                  "Events",
                                  "Estimated events",
                                ].map((label) => (
                                  <th key={label}>{label}</th>
                                ))}
                              </tr>
                            </thead>
                            <tbody>
                              {usage.map((row) => (
                                <tr key={row.operation}>
                                  {[
                                    "operation",
                                    "input_tokens",
                                    "output_tokens",
                                    "events",
                                    "estimated_events",
                                  ].map((key) => (
                                    <td key={key}>
                                      {typeof row[key] === "number"
                                        ? row[key].toLocaleString()
                                        : row[key]}
                                    </td>
                                  ))}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                      {usage?.length === 0 && (
                        <p className="muted">
                          No token usage has been recorded yet.
                        </p>
                      )}
                    </>
                  )}
                </div>
              </details>
              <Companies
                disabled={baseLocked}
                onDelete={(selections) =>
                  submit("/filings/delete", { selections })
                }
                completedDeletion={completedDeletion}
              />
            </div>
          </>
        }
      />
    </Suspense>
  );
}
