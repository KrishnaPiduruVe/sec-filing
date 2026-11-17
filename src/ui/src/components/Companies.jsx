import { useEffect, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import { request } from "../lib/api.js";
import { Processing } from "./Workflow.jsx";
export default function Companies({ disabled, completedDeletion }) {
  const [rows, setRows] = useState(null),
    [loading, setLoading] = useState(false),
    [error, setError] = useState("");
  const mounted = useRef(true),
    controller = useRef(null),
    lastDeletion = useRef(null);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      controller.current?.abort();
    };
  }, []);
  async function load() {
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    setLoading(true);
    setError("");
    try {
      const data = await request("/research/catalog", { signal: abort.signal });
      if (mounted.current)
        setRows(data.companies.map((company) => ({ Ticker: company.ticker })));
    } catch (e) {
      if (e.name !== "AbortError" && mounted.current) setError(e.message);
    } finally {
      if (mounted.current && !abort.signal.aborted) setLoading(false);
    }
  }
  useEffect(() => {
    if (completedDeletion && lastDeletion.current !== completedDeletion) {
      lastDeletion.current = completedDeletion;
      load();
    }
  }, [completedDeletion]);
  return (
    <details className="section-disclosure">
      <summary>Available company information</summary>
      <div className="disclosure-body">
        <button
          type="button"
          className="secondary"
          disabled={disabled || loading}
          onClick={load}
        >
          <RefreshCw size={16} />
          {rows === null ? "Show companies" : "Refresh companies"}
        </button>
        {loading ? (
          <Processing>Loading saved companies…</Processing>
        ) : (
          <>
            {error && (
              <p className="error" role="alert">
                {error}
              </p>
            )}
            {rows?.length > 0 && (
              <ul
                className="saved-tickers"
                aria-label="Available company tickers"
              >
                {[...new Set(rows.map((row) => row.Ticker).filter(Boolean))]
                  .sort()
                  .map((ticker) => (
                    <li key={ticker}>{ticker}</li>
                  ))}
              </ul>
            )}
            {rows?.length === 0 && (
              <p className="notice">
                No company information is available yet. Add a company to start
                your research.
              </p>
            )}
          </>
        )}
      </div>
    </details>
  );
}
