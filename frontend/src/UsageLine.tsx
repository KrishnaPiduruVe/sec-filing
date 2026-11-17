import { useEffect, useState } from "react";
import { getUsage } from "./api";
import type { UsageReport } from "./types";

function dollars(cost: number): string {
  return cost > 0 && cost < 0.000001 ? "< $0.000001" : `≈ $${cost.toFixed(6)}`;
}

export function UsageLine({ jobId }: { jobId: string }) {
  const [report, setReport] = useState<UsageReport>();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    void getUsage(jobId, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setReport(data);
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => controller.abort();
  }, [jobId]);

  const models = report?.models ?? [];
  if (!models.length) {
    return <div className="usage-line">{report || failed ? "Usage unavailable" : "Loading usage…"}</div>;
  }

  const input = models.reduce((total, row) => total + row.input_tokens, 0);
  const output = models.reduce((total, row) => total + row.output_tokens, 0);
  const cost = models.reduce((total, row) => total + (row.cost_usd ?? 0), 0);
  const priced = models.some((row) => row.cost_usd !== null);
  const partial = models.some((row) => row.unpriced_events > 0);
  const estimated = models.some((row) => row.estimated_events > 0);

  return (
    <div className="usage-line">
      {estimated ? "≈ " : ""}{(input + output).toLocaleString()} tokens
      {" · "}{priced ? dollars(cost) + (partial ? " (partial)" : "") : "Cost unavailable"}
      {" · "}{models.map(({ model }) => model).join(", ")}
    </div>
  );
}
