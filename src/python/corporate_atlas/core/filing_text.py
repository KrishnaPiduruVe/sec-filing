"""Normalize filing HTML and split it into overlapping text chunks."""
import re
from bs4 import BeautifulSoup


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for element in soup(["script", "style", "noscript"]):
        element.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
    if not text:
        raise ValueError("The filing HTML contained no readable text.")
    return text


def chunk_text(text: str, chunk_size: int = 4_000, overlap: int = 400) -> list[str]:
    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("Require chunk_size > overlap >= 0.")
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(text):
            break
        start = end - overlap
    return chunks
