import type { ChartPoint } from "./types";

type Props = {
  points: ChartPoint[];
  currency: string;
};

const width = 900;
const height = 265;
const padding = { top: 16, right: 12, bottom: 30, left: 62 };

function price(value: number, currency: string): string {
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency,
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${currency} ${value.toFixed(2)}`;
  }
}

export default function Chart({ points, currency }: Props) {
  if (!points.length) {
    return <div className="chart-empty">Price history isn’t available for this period.</div>;
  }

  const candles = points.some((point) => point.open != null && point.high != null && point.low != null);
  const values = points.flatMap((point) => [
    point.high ?? point.close,
    point.low ?? point.close,
    point.close,
  ]);
  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const span = Math.max(rawMax - rawMin, rawMax * 0.006, 0.01);
  const min = rawMin - span * 0.12;
  const max = rawMax + span * 0.12;
  const plotWidth = width - padding.left - padding.right;
  const volumeHeight = candles ? 36 : 0;
  const plotHeight = height - padding.top - padding.bottom - volumeHeight - (candles ? 8 : 0);
  const volumeTop = padding.top + plotHeight + 8;
  const volumeMax = Math.max(...points.map((point) => point.volume ?? 0), 1);
  const barWidth = Math.max(2, Math.min(10, (plotWidth / points.length) * 0.55));
  const yForPrice = (value: number) => padding.top + ((max - value) / (max - min)) * plotHeight;
  const coordinates = points.map((point, index) => ({
    x: padding.left + (points.length === 1 ? plotWidth / 2 : (index / (points.length - 1)) * plotWidth),
    y: yForPrice(point.close),
    point,
  }));
  const line = coordinates.map(({ x, y }, index) => `${index ? "L" : "M"}${x},${y}`).join(" ");
  const last = coordinates[coordinates.length - 1];
  const area = `${line} L${last.x},${padding.top + plotHeight} L${coordinates[0].x},${padding.top + plotHeight} Z`;
  const axisValues = [max, max - (max - min) / 2, min];
  const labelIndexes = Array.from(new Set([0, Math.floor((points.length - 1) / 2), points.length - 1]));

  return (
    <div className="chart-wrap">
      <svg className="price-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={candles ? "Stock candlestick price history" : "Stock closing price history"}>
        <defs>
          <linearGradient id="chart-area" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#32c48d" stopOpacity=".22" />
            <stop offset="100%" stopColor="#32c48d" stopOpacity="0" />
          </linearGradient>
        </defs>
        {axisValues.map((value, index) => {
          const y = padding.top + (index / 2) * plotHeight;
          return (
            <g key={value}>
              <line x1={padding.left} x2={width - padding.right} y1={y} y2={y} className="chart-grid" />
              <text x={padding.left - 10} y={y + 4} textAnchor="end" className="chart-axis">
                {price(value, currency)}
              </text>
            </g>
          );
        })}
        {candles ? (
          <>
            {coordinates.map(({ x, point }, index) => {
              const open = point.open ?? point.close;
              const high = point.high ?? Math.max(open, point.close);
              const low = point.low ?? Math.min(open, point.close);
              const rising = point.close >= open;
              const yOpen = yForPrice(open);
              const yClose = yForPrice(point.close);
              const color = rising ? "#55d19e" : "#ef817a";
              const volume = point.volume ?? 0;
              return (
                <g key={point.timestamp}>
                  <line x1={x} x2={x} y1={yForPrice(high)} y2={yForPrice(low)} stroke={color} className="chart-candle-wick" />
                  <rect
                    x={x - barWidth / 2}
                    y={Math.min(yOpen, yClose)}
                    width={barWidth}
                    height={Math.max(Math.abs(yOpen - yClose), 1)}
                    fill={color}
                    className="chart-candle-body"
                  />
                  {volume > 0 && (
                    <rect
                      x={x - barWidth / 2}
                      y={padding.top + plotHeight + 8 + volumeHeight * (1 - volume / volumeMax)}
                      width={barWidth}
                      height={volumeHeight * volume / volumeMax}
                      fill={color}
                      className="chart-volume-bar"
                    />
                  )}
                  <title>{`${new Date(point.timestamp).toLocaleDateString()}: O ${price(open, currency)} H ${price(high, currency)} L ${price(low, currency)} C ${price(point.close, currency)}`}</title>
                  <desc>{`Trading session ${index + 1} of ${points.length}`}</desc>
                </g>
              );
            })}
            <line x1={padding.left} x2={width - padding.right} y1={volumeTop} y2={volumeTop} className="chart-volume-divider" />
          </>
        ) : (
          <>
            <path d={area} fill="url(#chart-area)" />
            <path d={line} className="chart-line" />
            <circle cx={last.x} cy={last.y} r="4.5" className="chart-dot" />
          </>
        )}
        {labelIndexes.map((pointIndex, index) => {
          const point = points[pointIndex];
          return (
            <text
              key={point.timestamp}
              x={coordinates[pointIndex].x}
              y={height - 7}
              textAnchor={index === 0 ? "start" : index === labelIndexes.length - 1 ? "end" : "middle"}
              className="chart-axis"
            >
              {new Date(point.timestamp).toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" })}
            </text>
          );
        })}
      </svg>
    </div>
  );
}
