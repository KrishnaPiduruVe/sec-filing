type ChartSpec = {
  type: "bar" | "line" | "pie" | "doughnut" | "area" | "scatter";
  title: string;
  unit: string;
  categories: string[];
  values: number[];
  xValues?: number[];
};

function chartNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && Math.abs(value) <= 1e15;
}

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
      || !chart.values.every(chartNumber)
    ) {
      continue;
    }
    const type = chart.type ?? "bar";
    if (type !== "bar" && type !== "line" && type !== "pie" && type !== "doughnut" && type !== "area" && type !== "scatter") continue;
    if ((type === "pie" || type === "doughnut") && (chart.values.some((value) => value < 0) || !chart.values.some((value) => value > 0))) continue;
    const xValues = chart.x_values;
    if (type === "scatter" && (!Array.isArray(xValues) || xValues.length !== chart.values.length || !xValues.every(chartNumber))) continue;
    charts.push({
      type,
      xValues: type === "scatter" && Array.isArray(xValues) ? xValues : undefined,
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
  const yValues = chart.type === "area" ? [0, ...chart.values] : chart.values;
  const min = Math.min(...yValues);
  const max = Math.max(...yValues);
  const span = max - min;
  const xValues = chart.xValues ?? chart.values.map((_, index) => index);
  const xMin = Math.min(...xValues);
  const xMax = Math.max(...xValues);
  const xSpan = xMax - xMin;
  const points = chart.values.map((value, index) => ({
    x: xSpan ? left + ((xValues[index] - xMin) / xSpan) * (right - left) : (left + right) / 2,
    y: span ? bottom - ((value - min) / span) * (bottom - top) : (top + bottom) / 2,
    value,
    label: chart.categories[index],
  }));
  const format = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 2 });
  const ticks = span ? [max, (min + max) / 2, min] : [min];
  const trace = points.map(({ x, y }) => `${x},${y}`).join(" ");
  const zeroY = span ? bottom + min / span * (bottom - top) : bottom;

  return (
    <figure className="assistant-bar-chart">
      <figcaption><strong>{chart.title}</strong>{chart.unit && <span>{chart.unit}</span>}</figcaption>
      <svg viewBox="0 0 460 168" role="img" aria-label={`${chart.title} ${chart.type} chart${chart.unit ? ` in ${chart.unit}` : ""}`}>
        {ticks.map((value, index) => {
          const y = span ? top + index * (bottom - top) / 2 : points[0].y;
          return (
            <g key={value}>
              <line className="chart-grid" x1={left} x2={right} y1={y} y2={y} />
              <text className="bar-chart-category" x={left - 8} y={y + 4} textAnchor="end">{format.format(value)}</text>
            </g>
          );
        })}
        {chart.type === "area" && (
          <polygon className="assistant-chart-area" points={
            `${left},${zeroY} ${trace} ${right},${zeroY}`
          } />
        )}
        {chart.type !== "scatter" && <polyline className="chart-line" points={trace} />}
        {chart.type === "scatter" && (xSpan ? [xMin, (xMin + xMax) / 2, xMax] : [xMin]).map((value) => (
          <text key={value} className="bar-chart-category" x={xSpan ? left + ((value - xMin) / xSpan) * (right - left) : (left + right) / 2}
            y={bottom + 19} textAnchor="middle">{format.format(value)}</text>
        ))}
        {points.map(({ x, y, value, label }, index) => (
          <g key={`${label}-${index}`}>
            <circle className="chart-dot" cx={x} cy={y} r="4">
              <title>{`${label} · ${chart.type === "scatter" ? `${xValues[index].toLocaleString()}, ` : ""}${value.toLocaleString()}${chart.unit ? ` ${chart.unit}` : ""}`}</title>
            </circle>
            {chart.type !== "scatter" && (index === 0 || index === points.length - 1 || index === Math.floor(points.length / 2)) && (
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

const sliceColors = ["#38b88e", "#718df0", "#ed9b56", "#ca78bd", "#45b9cd", "#d9b648",
  "#7fbf62", "#ed7973", "#a08be6", "#5694c8", "#bf825f", "#749b94"];

export function PieChart({ chart }: { chart: ChartSpec }) {
  const total = chart.values.reduce((sum, value) => sum + value, 0);
  let start = 0;
  const radius = 87;
  const point = (angle: number) => [100 + radius * Math.sin(angle), 100 - radius * Math.cos(angle)].join(",");
  const percent = new Intl.NumberFormat(undefined, { style: "percent", maximumFractionDigits: 1 });

  return (
    <figure className="assistant-bar-chart">
      <figcaption><strong>{chart.title}</strong>{chart.unit && <span>{chart.unit}</span>}</figcaption>
      <div className="assistant-pie">
        <svg viewBox="0 0 200 200" role="img" aria-label={`${chart.title} ${chart.type} chart`}>
          {chart.values.map((value, index) => {
            if (value === 0) return null;
            const angle = value / total * 2 * Math.PI;
            const from = point(start);
            start += angle;
            const color = sliceColors[index];
            const title = `${chart.categories[index]} · ${percent.format(value / total)}`;
            return value === total
              ? <circle key={index} cx="100" cy="100" r={radius} fill={color}><title>{title}</title></circle>
              : <path key={index} d={`M100,100 L${from} A${radius},${radius} 0 ${angle > Math.PI ? 1 : 0},1 ${point(start)} Z`} fill={color}><title>{title}</title></path>;
          })}
          {chart.type === "doughnut" && <circle cx="100" cy="100" r="50" className="assistant-doughnut-hole" />}
        </svg>
        <ul className="assistant-pie-legend">
          {chart.categories.map((category, index) => (
            <li key={`${category}-${index}`}>
              <span aria-hidden="true" className="assistant-pie-swatch" style={{ backgroundColor: sliceColors[index] }} />
              <span>{category}</span>
              <strong>{percent.format(chart.values[index] / total)}</strong>
            </li>
          ))}
        </ul>
      </div>
    </figure>
  );
}
