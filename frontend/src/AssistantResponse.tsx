import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { BarChart, LineChart, parseAssistantCharts, PieChart } from "./BarChart";

function Charts({ source }: { source: string }) {
  const charts = parseAssistantCharts(source);
  if (!charts) return <p>Chart unavailable for this response.</p>;

  return (
    <div className="assistant-charts">
      {charts.map((chart, index) => {
        const Component = chart.type === "pie" || chart.type === "doughnut"
          ? PieChart
          : chart.type === "bar" ? BarChart : LineChart;
        return <Component key={`${chart.title}-${index}`} chart={chart} />;
      })}
    </div>
  );
}

export function AssistantResponse({ content }: { content: string }) {
  return (
    <ReactMarkdown
      skipHtml
      remarkPlugins={[remarkGfm]}
      components={{
        pre({ node }) {
          const block = node?.children[0];
          if (block?.type !== "element" || block.tagName !== "code") return null;
          const classes = block.properties.className;
          const source = block.children.map((child) => child.type === "text" ? child.value : "").join("");
          const isChart = Array.isArray(classes) && classes.includes("language-atlas-chart");
          return isChart || /^\s*\{\s*"charts"\s*:/.test(source) ? <Charts source={source} /> : null;
        },
        code() {
          return null;
        },
        p({ node, children }) {
          const first = node?.children[0];
          if (first?.type === "text" && /^\s*\{\s*"charts"\s*:/.test(first.value)) {
            return <Charts source={first.value} />;
          }
          return <p>{children}</p>;
        },
      }}
    >{content}</ReactMarkdown>
  );
}
