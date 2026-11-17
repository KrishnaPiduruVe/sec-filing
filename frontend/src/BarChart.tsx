type BarChartSpec = {
  title: string;
  unit: string;
  categories: string[];
  values: number[];
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function parseAssistantCharts(value: string): BarChartSpec[] | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    return null;
  }
  if (!isRecord(parsed) || !Array.isArray(parsed.charts) || parsed.charts.length > 8) {
    return null;
  }
  const charts: BarChartSpec[] = [];
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
      title: chart.title.slice(0, 120),
      unit: chart.unit.slice(0, 80),
      categories: chart.categories,
      values: chart.values,
    });
  }
  return charts.length ? charts : null;
}

export function BarChart({ chart }: { chart: BarChartSpec }) {
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
