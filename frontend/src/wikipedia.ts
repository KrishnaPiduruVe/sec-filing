import type { CompanyOverviewData } from "./types";

const legalSuffixes = new Set(["inc", "incorporated", "corp", "corporation", "ltd", "limited", "plc", "llc"]);

function normalizeName(name: string, stripSuffixes = true): string {
  const words = name.toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? [];
  while (stripSuffixes && words.length && legalSuffixes.has(words[words.length - 1])) {
    words.pop();
  }
  return words.join(" ");
}

type WikipediaPage = {
  title: string;
  extract?: string;
  fullurl?: string;
  pageprops?: Record<string, unknown>;
};

export async function getWikipediaProfile(
  companyName: string, signal: AbortSignal,
): Promise<CompanyOverviewData["profile"]> {
  const name = normalizeName(companyName);
  if (!name) return null;

  const params = new URLSearchParams({
    origin: "*",
    action: "query",
    format: "json",
    formatversion: "2",
    generator: "search",
    gsrsearch: `intitle:"${name}"`,
    gsrlimit: "5",
    prop: "extracts|info|pageprops",
    exintro: "1",
    explaintext: "1",
    exsentences: "8",
    exlimit: "5",
    inprop: "url",
    ppprop: "disambiguation",
  });
  const response = await fetch(`https://en.wikipedia.org/w/api.php?${params}`, {
    signal,
    credentials: "omit",
    referrerPolicy: "no-referrer",
  });
  if (!response.ok) throw new Error("Wikipedia profile is unavailable.");
  const data: { query?: { pages?: WikipediaPage[] } } = await response.json();
  const matches = (data.query?.pages ?? []).filter((page) =>
    normalizeName(page.title) === name
    && !Object.hasOwn(page.pageprops ?? {}, "disambiguation")
    && page.fullurl?.startsWith("https://en.wikipedia.org/wiki/")
    && /\b(company|corporation|conglomerate|manufacturer|bank|enterprise|operator)\b/i.test(page.extract?.split("\n", 1)[0] ?? ""),
  );
  const legalName = normalizeName(companyName, false);
  const exactMatches = matches.filter(({ title }) => normalizeName(title, false) === legalName);
  const candidates = exactMatches.length ? exactMatches : matches;
  const page = candidates.length === 1 ? candidates[0] : null;
  return page?.extract && page.fullurl ? { text: page.extract.trim(), source: page.fullurl } : null;
}
