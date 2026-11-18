"""Chart format shared by chat prompts and rendered by the frontend."""

CHART_INSTRUCTIONS = (
    'When a chart is requested, include a fenced atlas-chart JSON block shaped as '
    '{"charts":[{"type":"line","title":"...","unit":"...",'
    '"categories":["...","..."],"values":[1,2]}]}. '
    'Use type "line" by default. Match requested types when supported: "bar", "pie", '
    '"doughnut", "area", or "scatter". Pie and doughnut charts require non-negative '
    'parts of a single total. Scatter charts require numeric x_values aligned with values. '
    'If the requested type is unsupported or the source is unsuitable, explain and use a suitable '
    'supported chart or a table. Use 2–12 comparable data points per chart, '
    'align periods and units, and only chart numeric values supported by the source. '
    'Put a concise explanation and a Markdown table of the source values outside the chart block. '
    'Never output code or SQL in the answer. The atlas-chart block is the only permitted code fence. '
)
