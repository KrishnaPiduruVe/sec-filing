"""Chart format shared by chat prompts and rendered by the frontend."""

CHART_INSTRUCTIONS = (
    'When a chart is requested, include a fenced atlas-chart JSON block shaped as '
    '{"charts":[{"type":"line","title":"...","unit":"...",'
    '"categories":["...","..."],"values":[1,2]}]}. '
    'Use type "line" by default, '
    'and type "bar" when the user requests a bar chart. Use 2–12 comparable data points per chart, '
    'align periods and units, and only chart numeric values supported by the source. '
    'Put a concise explanation and a Markdown table of the source values outside the chart block. '
)
