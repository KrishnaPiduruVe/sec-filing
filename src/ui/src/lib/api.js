export async function request(path, { signal, ...options } = {}) {
  let response;
  try {
    response = await fetch(path, {
      ...options,
      signal,
      headers: {
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...options.headers,
      },
    });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new Error(
      "Unable to connect to Corporate Atlas. Check that python run_app.py is running.",
    );
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(body.detail)
      ? body.detail.map((item) => item.msg).join("; ")
      : body.detail;
    throw new Error(
      detail || `The request failed (${response.status}). Please try again.`,
    );
  }
  return body;
}
export const startJob = (path, data) =>
  request(path, { method: "POST", body: JSON.stringify(data) });
export const isBusy = (job) => ["running", "stopping"].includes(job?.status);
export const filingKey = (row) => `${row.Ticker}:${row.Accession}`;
export function selectedFilings(rows, keys) {
  return rows
    .filter((row) => keys.has(filingKey(row)))
    .map((row) => ({ ticker: row.Ticker, accession: row.Accession }));
}
export function saveText(text) {
  const url = URL.createObjectURL(
    new Blob([text], { type: "text/plain;charset=utf-8" }),
  );
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "corporate-atlas-answer.txt";
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
