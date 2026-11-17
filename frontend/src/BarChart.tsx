type ChartSpec = {
  type: "bar" | "line";
  title: string;
  unit: string;
  categories: string[];
  values: number[];
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function parseAssistantCharts(value: string): ChartSpec[] | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    return null;
  }
  if (!isRecord(parsed) || !Array.isArray(parsed.charts) || parsed.charts.length > 8) {
    return null;
  }
  const charts: ChartSpec[] = [];
  for (const chart of parsed.charts) {
    if (
      !isRecord(chart)
      || typeof chart.title !== "string"
      || typeof chart.unit !== "string"
      || !Array.isArray(chart.categories)
      || chart.categories.length < 2
      || chart.categories.length > 12
      || !chart.categories.every((category) => typeof category === "string" && category.length > 0 && category.length <= 100)
      || !Array.isArray(chart.values)
      || chart.values.length !== chart.categories.length
      || !chart.values.every((value) => typeof value === "number" && Number.isFinite(value) && Math.abs(value) <= 1e15)
    ) {
      return null;
    }
    charts.push({
      type: chart.type === "line" ? "line" : "bar",
      title: chart.title.slice(0, 120),
      unit: chart.unit.slice(0, 80),
      categories: chart.categories,
      values: chart.values,
    });
  }
  return charts.length ? charts : null;
}

export function BarChart({ chart }: { chart: ChartSpec }) {
  const width = 760;
  const left = 160;
  const right = 735;
  const top = 34;
  const rowHeight = 42;
  const height = top + chart.categories.length * rowHeight + 18;
  const minValue = Math.min(0, ...chart.values);
  const maxValue = Math.max(0, ...chart.values);
  const span = maxValue - minValue || 1;
  const xFor = (value: number) => left + ((value - minValue) / span) * (right - left);
  const zeroX = xFor(0);

  return (
    <figure className="assistant-bar-chart">
      <figcaption>
        <strong>{chart.title}</strong>
        {chart.unit && <span>{chart.unit}</span>}
      </figcaption>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`${chart.title} bar chart${chart.unit ? ` in ${chart.unit}` : ""}`}
      >
        <line className="bar-chart-zero" x1={zeroX} x2={zeroX} y1={top - 12} y2={height - 12} />
        {chart.categories.map((category, index) => {
          const value = chart.values[index];
          const y = top + index * rowHeight;
          const valueX = xFor(value);
          const barX = Math.min(zeroX, valueX);
          const barWidth = Math.max(Math.abs(valueX - zeroX), 1);
          const positive = value >= 0;
          return (
            <g key={`${category}-${index}`}>
              <text className="bar-chart-category" x={left - 12} y={y + 5} textAnchor="end">
                <title>{category}</title>
                {category.length > 22 ? `${category.slice(0, 21)}…` : category}
              </text>
              <rect
                className={positive ? "bar-chart-bar positive" : "bar-chart-bar negative"}
                x={barX}
                y={y - 10}
                width={barWidth}
                height={20}
                rx={4}
              />
              <text
                className="bar-chart-value"
                x={valueX + (positive ? 7 : -7)}
                y={y + 5}
                textAnchor={positive ? "start" : "end"}
              >
                {new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value)}
              </text>
            </g>
          );
        })}
      </svg>
    </figure>
  );
}

export function LineChart({ chart }: { chart: ChartSpec }) {
  const left = 56;
  const right = 404;
  const top = 24;
  const bottom = 138;
  const min = Math.min(...chart.values);
  const max = Math.max(...chart.values);
  const span = max - min;
  const points = chart.values.map((value, index) => ({
    x: left + (index / (chart.values.length - 1)) * (right - left),
    y: span ? bottom - ((value - min) / span) * (bottom - top) : (top + bottom) / 2,
    value,
    label: chart.categories[index],
  }));
  const format = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 2 });
  const ticks = span ? [max, (min + max) / 2, min] : [min];

  return (
    <figure className="assistant-bar-chart">
      <figcaption><strong>{chart.title}</strong>{chart.unit && <span>{chart.unit}</span>}</figcaption>
      <svg viewBox="0 0 460 168" role="img" aria-label={`${chart.title} line chart${chart.unit ? ` in ${chart.unit}` : ""}`}>
        {ticks.map((value, index) => {
          const y = span ? top + index * (bottom - top) / 2 : points[0].y;
          return (
            <g key={value}>
              <line className="chart-grid" x1={left} x2={right} y1={y} y2={y} />
              <text className="bar-chart-category" x={left - 8} y={y + 4} textAnchor="end">{format.format(value)}</text>
            </g>
          );
        })}
        <polyline className="chart-line" points={points.map(({ x, y }) => `${x},${y}`).join(" ")} />
        {points.map(({ x, y, value, label }, index) => (
          <g key={`${label}-${index}`}>
            <circle className="chart-dot" cx={x} cy={y} r="4">
              <title>{`${label} · ${value.toLocaleString()}${chart.unit ? ` ${chart.unit}` : ""}`}</title>
            </circle>
            {(index === 0 || index === points.length - 1 || index === Math.floor(points.length / 2)) && (
              <text className="bar-chart-category" x={x} y={bottom + 19} textAnchor={
                index === 0 ? "start" : index === points.length - 1 ? "end" : "middle"
              }>{label.length > 14 ? `${label.slice(0, 13)}…` : label}</text>
            )}
          </g>
        ))}
      </svg>
    </figure>
  );
}
