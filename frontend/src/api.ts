import type { ChatMessage, ClientConfig, Company, CompanyOverviewData, Job, StockSnapshot, UsageReport } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail || `Request failed (${response.status}).`);
  }
  return response.json() as Promise<T>;
}

export function listCompanies(): Promise<{ companies: Company[] }> {
  return request("/stocks");
}

export function getClientConfig(): Promise<ClientConfig> {
  return request("/config");
}

export function getCompanyLabel(ticker: string, signal?: AbortSignal): Promise<{ label: string }> {
  return request(`/companies/${encodeURIComponent(ticker)}/label`, { signal });
}

export function getCompanyOverview(ticker: string, signal?: AbortSignal): Promise<CompanyOverviewData> {
  return request(`/companies/${encodeURIComponent(ticker)}/overview`, { signal });
}

export function stockSnapshot(ticker: string, range: string, signal?: AbortSignal): Promise<StockSnapshot> {
  return request(`/stocks/${encodeURIComponent(ticker)}?range=${encodeURIComponent(range)}`, { signal });
}

export function prepareSec(
  ticker: string,
  batchSize: number,
  batchDelay: number,
): Promise<Job> {
  return request("/prepare", {
    method: "POST",
    body: JSON.stringify({
      tickers: ticker,
      batch_size: batchSize,
      batch_delay: batchDelay,
    }),
  });
}

export function indexStock(ticker: string): Promise<Job> {
  return request("/stocks", {
    method: "POST",
    body: JSON.stringify({ tickers: ticker }),
  });
}

export function askQuestion(
  question: string,
  topK: number,
  history: Array<Pick<ChatMessage, "role" | "content">>,
): Promise<Job> {
  return request("/query", {
    method: "POST",
    body: JSON.stringify({ question, mode: "vector", top_k: topK, history }),
  });
}

export function askUsageQuestion(
  question: string,
  topK: number,
  history: Array<Pick<ChatMessage, "role" | "content">>,
): Promise<Job> {
  return request("/query", {
    method: "POST",
    body: JSON.stringify({ question, mode: "usage", top_k: topK, history }),
  });
}

export function getUsage(jobId: string, signal?: AbortSignal): Promise<UsageReport> {
  return request(`/usage?job_id=${encodeURIComponent(jobId)}`, { cache: "no-store", signal });
}

export function jobStatus(id: string): Promise<Job> {
  return request(`/jobs/${encodeURIComponent(id)}`);
}

export function cancelJob(id: string): Promise<Job> {
  return request(`/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST" });
}

export async function waitForJob(
  job: Job,
  onProgress: (message: string, latest: Job) => void,
  pollIntervalMs: number,
): Promise<Job> {
  let latest = job;
  while (latest.status === "running" || latest.status === "stopping") {
    await new Promise((resolve) => window.setTimeout(resolve, pollIntervalMs));
    latest = await jobStatus(job.id);
    onProgress(latest.output, latest);
  }
  if (latest.status !== "completed") {
    throw new Error(latest.output.trim() || `Task ${latest.status}.`);
  }
  return latest;
}
