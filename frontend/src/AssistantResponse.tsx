import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { BarChart, LineChart, parseAssistantCharts } from "./BarChart";

function Markdown({ children }: { children: string }) {
  return <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>;
}

export function AssistantResponse({ content }: { content: string }) {
  const chartFence = /```atlas-chart[ \t]*\r?\n([\s\S]*?)```/g;
  const output: ReactNode[] = [];
  let lastIndex = 0;
  let partIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = chartFence.exec(content)) !== null) {
    if (match.index > lastIndex) {
      output.push(<Markdown key={`markdown-${partIndex++}`}>{content.slice(lastIndex, match.index)}</Markdown>);
    }
    const charts = parseAssistantCharts(match[1]);
    if (charts) {
      output.push(
        <div className="assistant-charts" key={`charts-${partIndex++}`}>
          {charts.map((chart, index) => {
            const Component = chart.type === "line" ? LineChart : BarChart;
            return <Component key={`${chart.title}-${index}`} chart={chart} />;
          })}
        </div>,
      );
    } else {
      output.push(<Markdown key={`invalid-chart-${partIndex++}`}>{match[0]}</Markdown>);
    }
    lastIndex = chartFence.lastIndex;
  }
  if (lastIndex < content.length) {
    output.push(<Markdown key={`markdown-${partIndex}`}>{content.slice(lastIndex)}</Markdown>);
  }
  return <>{output.length ? output : <Markdown>{content}</Markdown>}</>;
}
