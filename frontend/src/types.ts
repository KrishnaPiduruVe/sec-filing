export type Company = {
  ticker: string;
  name: string;
  exchange?: string | null;
  updated_at?: string | null;
};

export type StockQuote = {
  symbol: string;
  name: string;
  exchange?: string | null;
  currency?: string | null;
  current_price?: number | null;
  previous_close?: number | null;
  open?: number | null;
  day_range?: string | null;
  fifty_two_week_range?: string | null;
  market_cap?: number | null;
  trailing_pe?: number | null;
  beta?: number | null;
  dividend_yield?: number | null;
  volume?: number | null;
  average_volume?: number | null;
  sector?: string | null;
  industry?: string | null;
  website?: string | null;
  long_business_summary?: string | null;
  quote_time?: number | null;
  market_state?: string | null;
  quote_source?: string | null;
  fundamentals_source?: "yahoo" | "unavailable" | null;
  fifty_two_week_high?: number | null;
  fifty_two_week_low?: number | null;
  price_to_book?: number | null;
};

export type ChartPoint = {
  timestamp: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number;
  volume: number | null;
};

export type StockSnapshot = {
  quote: StockQuote;
  chart: ChartPoint[];
};

export type ClientConfig = {
  indexing: {
    batch_size: number;
    batch_delay_seconds: number;
  };
  query: {
    top_k: number;
    max_question_chars: number;
    max_history_messages: number;
    max_history_message_chars: number;
  };
  frontend: {
    job_poll_interval_ms: number;
    stock_chart_ranges: string[];
  };
  market_data: {
    default_currency: string;
  };
};

export type Job = {
  id: string;
  action: string;
  status: "running" | "stopping" | "completed" | "failed" | "stopped";
  output: string;
  steps?: Record<string, { status: string; message: string }>;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  scope: "research" | "usage";
  usageJobId?: string;
};

export type UsageReport = {
  models: Array<{
    model: string;
    input_tokens: number;
    output_tokens: number;
    estimated_events: number;
    cost_usd: number | null;
    unpriced_events: number;
  }>;
};

export type AnnualFinancialPeriod = {
  period_end: string;
  currency: string;
  revenue: number;
  net_income: number | null;
  net_margin: number | null;
};

export type CompanyOverviewData = {
  financials: {
    periods: AnnualFinancialPeriod[];
    revenue_growth: number | null;
    source: string;
  } | null;
  profile: { text: string; source: string } | null;
};
