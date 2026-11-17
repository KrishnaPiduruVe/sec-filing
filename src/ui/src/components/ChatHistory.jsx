import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
export default function ChatHistory({ entries, error }) {
  return (
    <details className="chat-history section-disclosure">
      <summary>Recent questions ({entries.length}/10)</summary>
      <div className="disclosure-body">
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {!entries.length && (
          <p>
            No saved answers yet. Your last 10 completed questions and answers
            will appear here.
          </p>
        )}
        {entries.map((entry) => (
          <details className="history-entry" key={entry.id}>
            <summary>{entry.question}</summary>
            <p className="history-meta">
              {entry.tickers?.join(", ") || "Available company data"} ·{" "}
              {new Date(entry.completed_at * 1000).toLocaleString()}
            </p>
            <div className="answer-text">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  a: (props) => (
                    <a {...props} target="_blank" rel="noopener noreferrer" />
                  ),
                }}
              >
                {entry.answer}
              </ReactMarkdown>
            </div>
          </details>
        ))}
      </div>
    </details>
  );
}
