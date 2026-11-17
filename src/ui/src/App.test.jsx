import snapshots from "../../python/corporate_atlas/data/company_snapshots.json";
import {
  render,
  screen,
  waitFor,
  fireEvent,
  act,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App.jsx";
import Companies from "./components/Companies.jsx";
import Workflow, { BackgroundDownload } from "./components/Workflow.jsx";
import { selectedFilings } from "./lib/api.js";

let currentJob;
const row = {
  Ticker: "AAPL",
  "Fiscal quarter": "FY2026 Q3",
  Accession: "0000320193-26-000020",
  "Downloaded files": 1,
  "Vector chunks": 20,
};
function response(data) {
  return { ok: true, json: async () => data };
}
beforeEach(() => {
  localStorage.clear();
  currentJob = null;
  globalThis.fetch = vi.fn(async (path, options = {}) => {
    if (path === "/jobs/current") return response({ job: currentJob });
    if (path === "/research/catalog")
      return response({
        companies: Object.values(snapshots).map((company) => ({
          ...company,
          tracked: true,
        })),
      });
    if (path.startsWith("/research/companies/"))
      return response(
        snapshots[path.split("/").pop().split("?")[0]] || snapshots.AAPL,
      );

    if (path === "/filings") return response({ filings: [row] });
    if (path === "/usage")
      return response({
        rows: [
          {
            operation: "answer",
            input_tokens: 100,
            output_tokens: 20,
            events: 1,
            estimated_events: 0,
          },
        ],
      });
    if (path.startsWith("/companies/"))
      return response({ label: "Apple Inc. (AAPL)" });
    if (
      path === "/research/query" ||
      path === "/query" ||
      path === "/prepare" ||
      path === "/filings/delete"
    ) {
      const action = {
        "/query": "query",
        "/research/query": "query",
        "/prepare": "prepare",
        "/filings/delete": "delete_filings",
      }[path];
      currentJob = {
        id: "new-job",
        action,
        status: "running",
        output: "",
        elapsed: 0,
        started: Date.now() / 1000,
        tickers: ["AAPL"],
        steps: {
          download: { status: "running" },
          vector: { status: "pending" },
        },
      };
      return response(currentJob);
    }
    throw new Error("Unexpected URL " + path);
  });
});

async function renderExpanded() {
  const result = render(<App />);
  fireEvent.click(
    screen.queryByRole("button", { name: "Expand sidebar" }) ||
      (await screen.findByRole("button", { name: "Expand sidebar" })),
  );
  return result;
}

describe("Corporate Atlas React application", () => {
  it("opens with the research dashboard and toggles settings", async () => {
    await renderExpanded();
    const user = userEvent.setup();
    expect(
      await screen.findByRole("heading", { name: "Corporate Atlas" }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByLabelText("Settings")).toBeEnabled(),
    );
    await user.click(screen.getByLabelText("Settings"));
    expect(screen.getByLabelText("Answer using")).toHaveValue("vector");
    expect(screen.queryByLabelText("Theme")).not.toBeInTheDocument();
  });
  it("switches between light and dark and remembers the chosen mode", async () => {
    const first = await renderExpanded();
    const user = userEvent.setup();
    expect(screen.getByLabelText("Color mode")).toHaveValue("dark");
    await user.selectOptions(screen.getByLabelText("Color mode"), "light");
    expect(document.documentElement).toHaveAttribute("data-theme", "light");
    expect(localStorage.getItem("atlas-color-mode")).toBe("light");
    first.unmount();
    await renderExpanded();
    expect(screen.getByLabelText("Color mode")).toHaveValue("light");
    await user.selectOptions(screen.getByLabelText("Color mode"), "dark");
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
  });
  it("keeps all stocks closed until requested and selects the first company", async () => {
    await renderExpanded();
    const user = userEvent.setup();
    expect(
      screen.queryByRole("region", { name: "All stocks" }),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Browse all" }));
    expect(
      screen.getByRole("region", { name: "All stocks" }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: "Select AAPL" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.queryByRole("button", { name: "Data library" }),
    ).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("Filter stocks"), "semiconductors");
    expect(
      screen.getByRole("button", { name: "Open NVIDIA company" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Open Apple company" }),
    ).not.toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Open NVIDIA company" }),
    );
    expect(screen.getByRole("button", { name: "Select NVDA" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await user.click(screen.getByRole("button", { name: "Close all stocks" }));
    expect(
      screen.queryByRole("region", { name: "All stocks" }),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Browse all" }));
    expect(screen.queryByLabelText("Add a ticker")).not.toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "All stocks" }),
    ).toBeInTheDocument();
  });
  it("shows no starters when Chroma has no indexed companies", async () => {
    const base = fetch.getMockImplementation();
    fetch.mockImplementation((path, options) =>
      path === "/research/catalog"
        ? Promise.resolve(response({ companies: [] }))
        : base(path, options),
    );
    await renderExpanded();
    expect(
      await screen.findByText("No companies indexed yet"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Select AAPL" }),
    ).not.toBeInTheDocument();
  });

  it("contains sidebar wheel scrolling at its boundaries", async () => {
    await renderExpanded();
    const pane = screen.getByRole("complementary", {
      name: "Company controls",
    });
    Object.defineProperties(pane, {
      scrollHeight: { configurable: true, value: 800 },
      clientHeight: { configurable: true, value: 400 },
    });
    pane.scrollTop = 0;
    expect(fireEvent.wheel(pane, { deltaY: -100, cancelable: true })).toBe(
      false,
    );
    expect(fireEvent.wheel(pane, { deltaY: 100, cancelable: true })).toBe(true);
    pane.scrollTop = 400;
    expect(fireEvent.wheel(pane, { deltaY: 100, cancelable: true })).toBe(
      false,
    );
    expect(fireEvent.wheel(pane, { deltaY: -100, cancelable: true })).toBe(
      true,
    );
  });
  it("shows download stages, indexed chunk count, and elapsed time", () => {
    render(
      <BackgroundDownload
        job={{
          action: "prepare",
          status: "running",
          tickers: ["AAPL"],
          elapsed: 125,
          output: "Indexed 5/20 chunks",
          steps: {
            download: { status: "completed" },
            profile: { status: "completed" },
            vector: { status: "running" },
          },
        }}
      />,
    );
    expect(screen.getByText("Elapsed 2m 5s")).toBeInTheDocument();
    expect(screen.getByText(/5 \/ 20 chunks indexed/)).toBeInTheDocument();
    expect(
      screen.getByRole("progressbar", { name: "Preparation stages" }),
    ).toHaveAttribute("aria-valuenow", "2");
  });
  it("submits a question with retrieval settings, then shows the cleaned answer", async () => {
    await renderExpanded();
    const user = userEvent.setup();
    await waitFor(() =>
      expect(screen.getByLabelText("Your question")).toBeEnabled(),
    );
    await user.type(
      screen.getByLabelText("Your question"),
      "What are the risks?",
    );
    await user.click(screen.getByRole("button", { name: "Explore insights" }));
    expect(fetch).toHaveBeenCalledWith(
      "/research/query",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          question: "What are the risks?",
          mode: "vector",
          top_k: 12,
          company_tickers: ["AAPL"],
        }),
      }),
    );
    expect(screen.getByText("Fetching filing insights…")).toBeInTheDocument();
    currentJob = {
      ...currentJob,
      status: "completed",
      answer: "## Reported risks\n\n- Supply disruptions",
      finished_at: Date.now() / 1000,
    };
    await waitFor(
      () => expect(screen.getByText("Supply disruptions")).toBeInTheDocument(),
      { timeout: 2500 },
    );
  });
  it("prepares in the background while company navigation remains available", async () => {
    await renderExpanded();
    const user = userEvent.setup();
    await waitFor(() =>
      expect(screen.getByLabelText("Company ticker")).toBeEnabled(),
    );
    fireEvent.click(screen.getByText("Add a company to your research"));
    await user.type(screen.getByLabelText("Company ticker"), "AAPL");
    await user.click(screen.getByRole("button", { name: "Download" }));
    expect(fetch).toHaveBeenCalledWith(
      "/prepare",
      expect.objectContaining({
        body: JSON.stringify({
          tickers: "AAPL",
          batch_size: 5,
          batch_delay: 65,
        }),
      }),
    );
    await user.click(screen.getByRole("button", { name: "Select MSFT" }));
    expect(await screen.findByText("About Microsoft")).toBeInTheDocument();
    expect(screen.getByText(/Running in the background/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Expand sidebar" }));
    expect(screen.getByLabelText("Settings")).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "View token usage", hidden: true }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "Show companies", hidden: true }),
    ).toBeEnabled();
    expect(screen.getByRole("button", { name: "Download" })).toBeDisabled();
    currentJob = {
      ...currentJob,
      status: "completed",
      finished_at: Date.now() / 1000,
    };
    fireEvent.click(screen.getByText("Available company information"));
    const inventory = await screen.findByRole(
      "list",
      { name: "Available company tickers" },
      { timeout: 3000 },
    );
    expect(inventory).toHaveTextContent("AAPL");
    expect(
      screen.queryByText(/Running in the background/),
    ).not.toBeInTheDocument();

    expect(
      screen.queryByRole("button", { name: "Stop preparation" }),
    ).not.toBeInTheDocument();
  });
  it("answers from available data while keeping download progress visible", async () => {
    const download = {
      id: "background-task",
      action: "prepare",
      status: "running",
      elapsed: 65,
      tickers: ["IBM"],
      steps: {
        download: { status: "completed" },
        profile: { status: "completed" },
        vector: { status: "running" },
      },
    };
    currentJob = download;
    const base = fetch.getMockImplementation();
    let query = null;
    fetch.mockImplementation(async (path, options = {}) => {
      if (path === "/jobs/current")
        return response({ job: download, query_job: query });
      if (path === "/research/query" && options.method === "POST") {
        query = {
          id: "answer-task",
          action: "query",
          status: "completed",
          started: Date.now() / 1000,
          answer: "An answer from available data.",
        };
        return response(query);
      }
      return base(path, options);
    });
    render(<App />);
    const user = userEvent.setup();
    await waitFor(() =>
      expect(screen.getByLabelText("Your question")).toBeEnabled(),
    );
    await user.type(screen.getByLabelText("Your question"), "Explain Apple");
    await user.click(screen.getByRole("button", { name: "Explore insights" }));
    expect(
      await screen.findByText("An answer from available data."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("status", { name: "Download progress" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Expand sidebar" }));
    fireEvent.click(screen.getByText("Add a company to your research"));
    expect(
      screen.getByRole("button", { name: "Download", exact: true }),
    ).toBeDisabled();
    expect(screen.getByLabelText("Settings")).toBeEnabled();
  });
  it("shows token usage as a table inside Usage", async () => {
    await renderExpanded();
    const user = userEvent.setup();
    fireEvent.click(screen.getByText("Usage"));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "View token usage" }),
      ).toBeEnabled(),
    );
    await user.click(screen.getByRole("button", { name: "View token usage" }));
    expect(
      await screen.findByRole("columnheader", { name: "Input tokens" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "100" })).toBeInTheDocument();
  });
  it("shows unique saved tickers and a loading state on every refresh", async () => {
    let resolve;
    fetch.mockImplementation(
      () =>
        new Promise((done) => {
          resolve = () =>
            done(
              response({
                companies: [{ ticker: "AAPL" }, { ticker: "AAPL" }],
              }),
            );
        }),
    );
    const onDelete = vi.fn();
    render(<Companies disabled={false} onDelete={onDelete} />);
    const user = userEvent.setup();
    fireEvent.click(screen.getByText("Available company information"));
    await user.click(screen.getByRole("button", { name: "Show companies" }));
    expect(screen.getByText("Loading saved companies…")).toBeInTheDocument();
    resolve();
    expect(await screen.findByText("AAPL")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(screen.queryByText("FY2026 Q3")).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Refresh companies" }));
    expect(screen.queryByText("FY2026 Q3")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Refresh companies" }),
    ).toBeDisabled();
    resolve();
    expect(await screen.findByText("AAPL")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Refresh companies" }),
    ).toBeEnabled();
  });
  it("hides completed preparation stages", () => {
    render(<Workflow job={{ action: "prepare", status: "completed" }} />);
    expect(
      screen.queryByText("Preparing your information"),
    ).not.toBeInTheDocument();
  });
  it("never expands a selected fiscal quarter into an entire-company deletion", () => {
    const old = { ...row, Accession: "0000320193-26-000001" };
    expect(
      selectedFilings([old, row], new Set([`AAPL:${row.Accession}`])),
    ).toEqual([{ ticker: "AAPL", accession: row.Accession }]);
  });
  it("removes the named preparation notice after ten seconds", async () => {
    vi.useFakeTimers();
    try {
      currentJob = {
        id: "prepared",
        action: "prepare",
        status: "completed",
        finished_at: Date.now() / 1000,
        tickers: ["AAPL"],
        steps: {},
      };
      render(<App />);
      await act(async () => {
        await Promise.resolve();
      });
      fireEvent.click(screen.getByRole("button", { name: "Expand sidebar" }));
      expect(screen.getByText(/Information for Apple Inc/)).toBeInTheDocument();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10001);
      });
      expect(
        screen.queryByText(/Information for Apple Inc/),
      ).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
  it("removes the deletion notice after five seconds", async () => {
    vi.useFakeTimers();
    try {
      currentJob = {
        id: "deleted",
        action: "delete_filings",
        status: "completed",
        finished_at: Date.now() / 1000,
        output: "Deleted selected quarter.",
      };
      render(<App />);
      await act(async () => {
        await Promise.resolve();
      });
      fireEvent.click(screen.getByRole("button", { name: "Expand sidebar" }));
      expect(screen.getByText("Deleted selected quarter.")).toBeInTheDocument();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5001);
      });
      expect(
        screen.queryByText("Deleted selected quarter."),
      ).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
  it("opens with source-backed company cards and switches the selected company", async () => {
    await renderExpanded();
    await screen.findByText(snapshots.AAPL.profile.description);
    expect(screen.getByText("Annual revenue")).toBeInTheDocument();
    expect(
      screen.queryByText("Wikimedia company overview"),
    ).not.toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Select MSFT" }));
    expect(await screen.findByText("About Microsoft")).toBeInTheDocument();
    expect(screen.queryByLabelText("Research scope")).not.toBeInTheDocument();
    await user.type(
      screen.getByLabelText("Your question"),
      "Explain the business",
    );
    await user.click(screen.getByRole("button", { name: "Explore insights" }));
    expect(fetch).toHaveBeenCalledWith(
      "/research/query",
      expect.objectContaining({
        body: JSON.stringify({
          question: "Explain the business",
          mode: "vector",
          top_k: 12,
          company_tickers: ["MSFT"],
        }),
      }),
    );
  });
  it("compares companies and keeps all selected tickers in assistant context", async () => {
    await renderExpanded();
    const user = userEvent.setup();
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Compare companies" }),
      ).toBeEnabled(),
    );
    await screen.findByText(snapshots.AAPL.profile.description);
    await user.click(screen.getByRole("button", { name: "Compare companies" }));
    expect(screen.getByText("Annual revenue comparison")).toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: /NVIDIA/ }));
    await user.click(
      screen.getByRole("button", { name: "Explore this comparison" }),
    );
    expect(screen.getByLabelText("Your question").value).toContain("NVDA");
    await user.click(screen.getByRole("button", { name: "Explore insights" }));
    expect(fetch).toHaveBeenCalledWith(
      "/research/query",
      expect.objectContaining({
        body: JSON.stringify({
          question: screen.getByLabelText("Your question").value,
          mode: "vector",
          top_k: 12,
          company_tickers: ["AAPL", "MSFT", "NVDA"],
        }),
      }),
    );
  });
  it("shows a dismissible popup when both sources have no usable content", async () => {
    currentJob = {
      id: "invalid-ticker-job",
      action: "prepare",
      status: "failed",
      finished_at: Date.now() / 1000,
      source_error: {
        message: "Check the ticker APPL.",
        sources: ["SEC EDGAR", "Wikimedia"],
      },
    };
    await renderExpanded();
    const user = userEvent.setup();
    expect(
      await screen.findByRole("alertdialog", { name: "Check the ticker" }),
    ).toHaveTextContent("SEC EDGAR");
    await user.click(
      screen.getByRole("button", { name: "Close", exact: true }),
    );
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("starts collapsed, removes search and workspace navigation, and opens controls on demand", async () => {
    render(<App />);
    const user = userEvent.setup();
    expect(
      screen.getByRole("button", { name: "Expand sidebar" }),
    ).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.queryByRole("button", { name: "Settings" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Workspace")).not.toBeInTheDocument();
    expect(screen.queryByText("Overview")).not.toBeInTheDocument();
    expect(screen.queryByText("Annual revenue growth")).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText("Find or add company"),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Expand sidebar" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Settings" })).toBeEnabled(),
    );
    expect(
      screen.queryByRole("button", { name: "Add company", exact: true }),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    expect(
      screen.queryByRole("button", { name: "Add company", exact: true }),
    ).not.toBeInTheDocument();
  });
  it("changes annual chart range and opens a company from the growth watchlist", async () => {
    await renderExpanded();
    const user = userEvent.setup();
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "3Y", exact: true }),
      ).toBeEnabled(),
    );
    await user.click(screen.getByRole("button", { name: "3Y", exact: true }));
    expect(
      screen.getByRole("button", { name: "3Y", exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByText("3 annual periods · fiscal year end"),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", {
        name: "Select TSLA",
      }),
    );
    expect(await screen.findByText("About Tesla")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Select TSLA" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(fetch.mock.calls.some(([path]) => path === "/research/query")).toBe(
      false,
    );
  });
});
