"""Fetch the latest SEC 10-Q filing and its PDF exhibits for each ticker."""

from __future__ import annotations

import argparse
import os
import re
import time
from pathlib import Path
from corporate_atlas.paths import DATA_ROOT
from typing import Any
from urllib.parse import quote

import requests
from dotenv import load_dotenv
from corporate_atlas.paths import ENV_FILE
from corporate_atlas.settings import SETTINGS

SEC_WWW = SETTINGS.sec.www_base_url
SEC_DATA = SETTINGS.sec.data_base_url
DEFAULT_TICKERS = tuple(SETTINGS.sec.default_tickers)
ACCESSION_PATTERN = re.compile(r"^\d{10}-\d{2}-\d{6}$")
EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")


def sec_user_agent() -> str:
    """Return a descriptive SEC User-Agent with a real contact email."""
    load_dotenv(ENV_FILE, override=False)
    user_agent = os.getenv(SETTINGS.sec.user_agent_env_var, "").strip()
    if (
        not user_agent
        or not EMAIL_PATTERN.search(user_agent)
        or "example.com" in user_agent.lower()
        or "your.email" in user_agent.lower()
    ):
        raise ValueError(
            f"Set {SETTINGS.sec.user_agent_env_var} in .env to an identifying name and a valid "
            "contact email, for example 'Analyst analyst@company.com'."
        )
    return user_agent


class SecClient:
    """Small, paced SEC HTTP client that sends the required User-Agent."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self._last_request_at = 0.0

    def get(self, url: str, *, stream: bool = False) -> requests.Response:
        elapsed = time.monotonic() - self._last_request_at
        if self._last_request_at and elapsed < SETTINGS.http.sec_min_interval_seconds:
            time.sleep(SETTINGS.http.sec_min_interval_seconds - elapsed)
        response = self.session.get(
            url,
            headers={
                "User-Agent": sec_user_agent(),
                "Accept-Encoding": "gzip, deflate",
                "Host": url.split("/")[2],
            },
            timeout=SETTINGS.http.sec_timeout_seconds,
            stream=stream,
        )
        self._last_request_at = time.monotonic()
        try:
            response.raise_for_status()
        except requests.RequestException:
            response.close()
            raise
        return response


def get_json(client: SecClient, url: str) -> dict[str, Any]:
    response = client.get(url)
    try:
        payload = response.json()
    finally:
        response.close()
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object from SEC endpoint: {url}")
    return payload


def ticker_cik_map(payload: dict[str, Any]) -> dict[str, str]:
    """Build a case-insensitive ticker-to-ten-digit-CIK map."""
    mapping: dict[str, str] = {}
    for company in payload.values():
        if not isinstance(company, dict):
            continue
        ticker = company.get("ticker")
        cik = company.get("cik_str")
        if ticker and cik is not None:
            mapping[str(ticker).upper()] = str(cik).zfill(10)
    return mapping


def latest_10q(recent_filings: dict[str, Any]) -> dict[str, str]:
    """Select the most recently filed exact 10-Q from submissions' recent data."""
    fields = ("form", "accessionNumber", "primaryDocument", "filingDate")
    columns = [recent_filings.get(field, []) for field in fields]
    if not all(isinstance(column, list) for column in columns):
        raise ValueError("SEC submissions response has malformed recent filings.")
    rows = [
        dict(zip(fields, values))
        for values in zip(*columns)
        if values[0] == "10-Q"
    ]
    if not rows:
        raise LookupError("No 10-Q filing was found in the SEC submissions data.")
    rows.sort(key=lambda row: row["filingDate"], reverse=True)
    filing = rows[0]
    if not filing["accessionNumber"] or not filing["primaryDocument"]:
        raise ValueError("Latest 10-Q filing is missing its accession or primary document.")
    if not ACCESSION_PATTERN.fullmatch(filing["accessionNumber"]):
        raise ValueError(f"Unexpected SEC accession number: {filing['accessionNumber']!r}")
    primary_document = Path(filing["primaryDocument"]).name
    if not primary_document.lower().endswith((".htm", ".html")):
        raise ValueError(f"The primary 10-Q document is not HTML: {primary_document}")
    filing["primaryDocument"] = primary_document
    return filing


def archive_url(cik: str, accession: str) -> str:
    path = SETTINGS.sec.archive_path.format(
        cik=int(cik),
        accession=accession.replace("-", ""),
    )
    return f"{SEC_WWW}{path}"


def filing_pdf_names(index: dict[str, Any]) -> list[str]:
    directory = index.get("directory", {})
    items = directory.get("item", []) if isinstance(directory, dict) else []
    return sorted(
        {
            Path(str(item.get("name", ""))).name
            for item in items
            if isinstance(item, dict)
            and str(item.get("name", "")).lower().endswith(".pdf")
        }
    )


def download_file(client: SecClient, url: str, destination: Path) -> None:
    """Stream a SEC file to disk and replace it atomically when complete."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".part")
    response = client.get(url, stream=True)
    try:
        with temporary.open("wb") as output:
            for block in response.iter_content(
                chunk_size=SETTINGS.http.sec_download_chunk_bytes
            ):
                if block:
                    output.write(block)
        temporary.replace(destination)
    finally:
        response.close()
        if temporary.exists():
            temporary.unlink()


def fetch_ticker(
    ticker: str,
    client: SecClient,
    ticker_map: dict[str, str],
    output_dir: Path,
) -> Path:
    normalized_ticker = ticker.upper()
    try:
        cik = ticker_map[normalized_ticker]
    except KeyError as exc:
        raise LookupError(f"Ticker {normalized_ticker!r} was not found by the SEC.") from exc

    submissions_path = SETTINGS.sec.submissions_path.format(cik=cik)
    submissions = get_json(client, f"{SEC_DATA}{submissions_path}")
    recent = submissions.get("filings", {}).get("recent")
    if not isinstance(recent, dict):
        raise ValueError(f"SEC submissions response has no recent filings for {normalized_ticker}.")
    filing = latest_10q(recent)
    accession = filing["accessionNumber"]
    base_url = archive_url(cik, accession)
    filing_dir = output_dir / normalized_ticker / accession
    filing_dir.mkdir(parents=True, exist_ok=True)

    primary_document = filing["primaryDocument"]
    download_file(
        client,
        f"{base_url}/{quote(primary_document)}",
        filing_dir / primary_document,
    )
    index = get_json(
        client,
        f"{base_url}/{SETTINGS.sec.filing_index_filename}",
    )
    for pdf_name in filing_pdf_names(index):
        download_file(client, f"{base_url}/{quote(pdf_name)}", filing_dir / pdf_name)
    return filing_dir


def fetch_filings(
    tickers: tuple[str, ...] | list[str] = DEFAULT_TICKERS,
    output_dir: Path = DATA_ROOT / SETTINGS.paths.filings_dir,
) -> list[Path]:
    client = SecClient()
    company_tickers = get_json(
        client,
        f"{SEC_WWW}{SETTINGS.sec.company_tickers_path}",
    )
    mapping = ticker_cik_map(company_tickers)
    return [fetch_ticker(ticker, client, mapping, output_dir) for ticker in tickers]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "tickers",
        nargs="*",
        default=list(DEFAULT_TICKERS),
        help=(
            "Company tickers to fetch (default: "
            + " ".join(DEFAULT_TICKERS)
            + ")"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DATA_ROOT / SETTINGS.paths.filings_dir,
    )
    args = parser.parse_args()
    for filing_dir in fetch_filings(args.tickers, args.output_dir):
        print(f"Saved filing to {filing_dir}")


if __name__ == "__main__":
    main()
