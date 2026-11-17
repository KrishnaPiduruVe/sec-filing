import {
  Check,
  LoaderCircle,
  AlertCircle,
  Download,
  Database,
  Globe2,
} from "lucide-react";
const stages = [
  ["download", "Download filings", Download],
  ["profile", "Company profile", Globe2],
  ["vector", "Build vector store", Database],
];
export function Processing({ children }) {
  return (
    <div className="processing" role="status">
      <LoaderCircle className="spin" size={18} />
      {children}
    </div>
  );
}
export default function Workflow({ job }) {
  if (!job || job.action !== "prepare" || job.status === "completed")
    return null;
  const completed = stages.filter(
    ([key]) => job.steps?.[key]?.status === "completed",
  ).length;
  return (
    <section className="workflow-panel" aria-label="Preparation progress">
      <div className="section-heading">
        <h3>Preparing your information</h3>
        <span>
          {completed} of {stages.length} complete
        </span>
      </div>
      <ol className="workflow">
        {stages.map(([key, title, Icon]) => {
          const step = job.steps?.[key] || { status: "pending" };
          const StateIcon =
            step.status === "completed"
              ? Check
              : ["failed", "stopped"].includes(step.status)
                ? AlertCircle
                : Icon;
          return (
            <li
              key={key}
              className={`stage ${step.status}`}
              aria-current={step.status === "running" ? "step" : undefined}
            >
              <div className="circle">
                <StateIcon size={23} />
              </div>
              <strong>{title}</strong>
              <small>
                {step.message ||
                  (step.status === "pending" ? "Waiting" : step.status)}
              </small>
            </li>
          );
        })}
      </ol>
      <div
        className="progress-track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={stages.length}
        aria-valuenow={completed}
      >
        <div style={{ width: `${(completed / stages.length) * 100}%` }} />
      </div>
      {["running", "stopping"].includes(job.status) && (
        <Processing>
          Preparing filing information…{" "}
          <span className="elapsed">
            {Math.floor(job.elapsed / 60)}m {job.elapsed % 60}s
          </span>
        </Processing>
      )}
      {job.status === "failed" && (
        <p className="error">
          Preparation failed. Newly created downloads are cleaned up where
          possible. Please review the details and retry.
        </p>
      )}
      {job.status === "stopped" && (
        <p className="muted">
          Preparation was interrupted. New downloads are cleaned up where
          possible.
        </p>
      )}
      {job.output?.includes("We already have") && (
        <p className="notice">
          {job.output
            .split("\n")
            .find((line) => line.startsWith("We already have"))}
        </p>
      )}
      <details className="logs">
        <summary>Preparation details</summary>
        <pre>{job.output || "Starting…"}</pre>
      </details>
    </section>
  );
}

export function BackgroundDownload({ job }) {
  if (!job || job.action !== "prepare") return null;
  const running = ["running", "stopping"].includes(job.status);
  const completed = job.status === "completed";
  const failed = ["failed", "stopped"].includes(job.status);
  if (completed && Date.now() - (job.finished_at || 0) * 1000 > 10000)
    return null;
  if (!running && !completed && !failed) return null;
  const current = stages.findIndex(
    ([key]) => job.steps?.[key]?.status === "running",
  );
  const done = completed
    ? stages.length
    : current >= 0
      ? current
      : stages.filter(([key]) => job.steps?.[key]?.status === "completed")
          .length;
  const elapsed = Math.max(0, Math.floor(job.elapsed || 0));
  const time = `${Math.floor(elapsed / 60)}m ${elapsed % 60}s`;
  const chunks = [
    ...(job.output || "").matchAll(/Indexed (\d+)\/(\d+) chunks/g),
  ].at(-1);
  const phase = completed
    ? "Company information ready"
    : failed
      ? "Download could not finish"
      : job.status === "stopping"
        ? "Stopping preparation"
        : current === 1
          ? "Fetching Wikimedia and company facts"
          : current === 2
            ? "Building the vector index"
            : "Downloading SEC filings";
  const StateIcon = completed ? Check : failed ? AlertCircle : LoaderCircle;
  return (
    <section
      className={`background-download download-dock ${failed ? "download-failed" : ""}`}
      aria-label="Download progress"
      role="status"
    >
      <div className="download-dock-heading">
        <StateIcon size={18} className={running ? "spin" : ""} />
        <strong>{job.tickers?.join(", ") || "Company download"}</strong>
        <span className="download-timer">
          {completed || failed ? "Time taken" : "Elapsed"} {time}
        </span>
      </div>
      <p>{phase}</p>
      <div
        className="download-stage-track"
        role="progressbar"
        aria-label="Preparation stages"
        aria-valuemin={0}
        aria-valuemax={stages.length}
        aria-valuenow={done}
      >
        {stages.map(([key, title], index) => (
          <span
            key={key}
            title={title}
            className={
              index < done ? "complete" : index === current ? "current" : ""
            }
          />
        ))}
      </div>
      <small>
        {running
          ? current === 2 && chunks
            ? `${chunks[1]} / ${chunks[2]} chunks indexed · `
            : `${done} / ${stages.length} stages complete · `
          : ""}
        {failed
          ? "Open the left pane for preparation details."
          : completed
            ? "Updated automatically."
            : "Running in the background."}
      </small>
    </section>
  );
}
