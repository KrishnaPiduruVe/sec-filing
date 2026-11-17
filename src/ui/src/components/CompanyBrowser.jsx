import { useState } from "react";
import { LoaderCircle, Plus, X } from "lucide-react";

export default function CompanyBrowser({
  companies,
  active,
  disabled,
  mutationDisabled = disabled,
  busy,
  onOpen,
  onAdd,
  onRemove,
  onClose,
}) {
  const [filter, setFilter] = useState("");
  const rows = companies.filter((c) =>
    `${c.ticker} ${c.name} ${c.sector || ""}`
      .toLowerCase()
      .includes(filter.trim().toLowerCase()),
  );
  return (
    <section className="company-browser dashboard-card" aria-label="All stocks">
      <div className="browser-toolbar">
        <h2>
          All stocks <span>({companies.length})</span>
        </h2>
        <input
          aria-label="Filter stocks"
          placeholder="Filter by name or sector"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <button
          type="button"
          className="text-button"
          aria-label="Close all stocks"
          onClick={onClose}
        >
          <X size={15} />
          Close
        </button>
      </div>
      {busy && (
        <p role="status" className="processing">
          <LoaderCircle size={16} className="spin" />
          Connecting company data…
        </p>
      )}
      <div className="browser-company-grid">
        {rows.map((c) => (
          <div
            className={`browser-company ${active === c.ticker ? "selected" : ""}`}
            key={c.ticker}
          >
            <button
              className="browser-company-open"
              disabled={disabled || (!c.tracked && mutationDisabled)}
              aria-label={`Open ${c.name} company`}
              aria-pressed={active === c.ticker}
              onClick={() => (c.tracked ? onOpen(c.ticker) : onAdd(c.ticker))}
            >
              <span>
                <b>{c.ticker}</b> {c.name}
              </span>
              <small>{c.sector || "Public company"}</small>
            </button>
          </div>
        ))}
        {!rows.length && (
          <p>
            No companies match this filter. You can add a company in the left
            pane.
          </p>
        )}
      </div>
      <p className="browser-note">
        Only companies with indexed content in Chroma are listed.
      </p>
    </section>
  );
}
