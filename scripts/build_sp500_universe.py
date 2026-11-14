#!/usr/bin/env python3
"""Build the Mag-500 S&P 500 universe snapshot (Phase 2 input).

Primary source: Wikipedia "List of S&P 500 companies" table (Symbol,
Security, GICS Sector, GICS Sub-Industry, CIK) — updated within days
of index changes. Cross-check: S&P Dow Jones Indices official
constituents spreadsheet (sp500.xlsx) when reachable; a mismatch is
reported in the provenance file, never silently merged.

Ranking: market-cap DESCENDING at snapshot time, via the batched
Robinhood fundamentals transport (20 symbols/call). Tickers keep dot
form (BRK.B, BF.B). Duplicates fail validation. The snapshot is
written in the PRD input envelope {"companies": [{rank, ticker,
name, sector}, ...]} to data/sp500_constituents.json, with provenance
in data/sp500_provenance.json.

If BOTH sources are unreachable this script exits non-zero and writes
nothing — a fabricated universe is worse than no universe.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
SPDJI_URL = "https://www.spglobal.com/spdji/en/idsexport/file.xls?redesignExport=true&languageId=1&indexId=5479673"
USER_AGENT = "Muse Mag-500 Universe Builder (contact: admin@example.com)"


def _fetch(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as fh:
        return fh.read()


class _FirstTableParser(HTMLParser):
    """Collect rows of the first wikitable (the constituents table)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._in_table = False
        self._done = False
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if self._done:
            return
        if tag == "table" and not self._in_table:
            cls = dict(attrs).get("class", "")
            if "wikitable" in cls:
                self._in_table = True
        elif self._in_table and tag == "tr":
            self._row = []
        elif self._in_table and tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if self._done or not self._in_table:
            return
        if tag == "table":
            self._in_table = False
            self._done = True
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
        elif tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def fetch_wikipedia() -> list[dict]:
    html = _fetch(WIKI_URL).decode("utf-8", "replace")
    parser = _FirstTableParser()
    parser.feed(html)
    rows = parser.rows
    if len(rows) < 400:
        raise ValueError(f"Wikipedia constituents table too small: {len(rows)} rows")
    header = [c.lower() for c in rows[0]]
    try:
        i_ticker = next(i for i, c in enumerate(header) if "symbol" in c)
        i_name = next(i for i, c in enumerate(header) if "security" in c)
        i_sector = next(i for i, c in enumerate(header) if c.strip() == "gics sector")
    except StopIteration as exc:
        raise ValueError(f"unexpected Wikipedia header: {header}") from exc
    out = []
    for row in rows[1:]:
        if len(row) <= max(i_ticker, i_name, i_sector):
            continue
        ticker = row[i_ticker].strip().upper()
        if not ticker or not re.fullmatch(r"[A-Z.\-]+", ticker):
            continue
        out.append({"ticker": ticker, "name": row[i_name].strip(),
                    "sector": row[i_sector].strip()})
    return out


def fetch_spdji_tickers() -> list[str] | None:
    """Best-effort cross-check list from the official S&P DJI export.
    The export is an Excel file; we only extract ticker-shaped tokens
    from its shared-strings — enough for a set comparison. Returns None
    when unreachable/unparseable (cross-check is optional)."""
    try:
        raw = _fetch(SPDJI_URL, timeout=30)
    except Exception:
        return None
    try:
        import io
        import zipfile
        tickers: set[str] = set()
        if zipfile.is_zipfile(io.BytesIO(raw)):
            import xml.etree.ElementTree as ET
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                names = [n for n in zf.namelist() if "sharedStrings" in n]
                if not names:
                    return None
                root = ET.fromstring(zf.read(names[0]))
                ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                for si in root.findall("m:si", ns):
                    text = "".join(t.text or "" for t in si.iter()
                                   if t.tag.endswith("}t"))
                    if re.fullmatch(r"[A-Z]{1,5}([.\-][A-Z])?", text.strip()):
                        tickers.add(text.strip())
        return sorted(tickers) if tickers else None
    except Exception:
        return None


def main() -> int:
    try:
        companies = fetch_wikipedia()
        source = WIKI_URL
    except Exception as wiki_exc:
        print(f"Wikipedia fetch failed: {wiki_exc!r}", file=sys.stderr)
        fallback = fetch_spdji_tickers()
        if not fallback:
            print("BLOCKED: both S&P 500 sources unreachable; no snapshot written.",
                  file=sys.stderr)
            return 1
        print("BLOCKED: official export gives tickers only (no name/sector); "
              "refusing to fabricate fields.", file=sys.stderr)
        return 1

    tickers = [c["ticker"] for c in companies]
    if len(tickers) != len(set(tickers)):
        dupes = sorted({t for t in tickers if tickers.count(t) > 1})
        print(f"duplicate tickers from source: {dupes}", file=sys.stderr)
        return 1

    cross = fetch_spdji_tickers()
    cross_note = None
    if cross:
        only_wiki = sorted(set(tickers) - set(cross))
        only_spdji = sorted(set(cross) - set(tickers))
        cross_note = {"only_in_wikipedia": only_wiki,
                      "only_in_spdji_export": only_spdji}
    else:
        cross_note = {"status": "spdji_export_unreachable_or_unparseable"}

    # Rank by market cap descending via batched Robinhood fundamentals.
    from scripts.robinhood_transport import fetch_fundamentals
    fundamentals = fetch_fundamentals(tickers)
    caps: dict[str, float | None] = {}
    for t in tickers:
        raw_cap = (fundamentals.get(t) or {}).get("market_cap")
        try:
            caps[t] = float(raw_cap) if raw_cap is not None else None
        except (TypeError, ValueError):
            caps[t] = None
    missing_caps = sorted(t for t, c in caps.items() if c is None)
    # Deterministic: cap desc, ticker asc as tie-break; missing caps last.
    ordered = sorted(companies,
                     key=lambda c: (-(caps[c["ticker"]] or 0.0), c["ticker"]))
    snapshot = {"companies": [
        {"rank": i, "ticker": c["ticker"], "name": c["name"],
         "sector": c["sector"]}
        for i, c in enumerate(ordered, 1)
    ]}
    built_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    (REPO_ROOT / "data").mkdir(parents=True, exist_ok=True)
    (REPO_ROOT / "data" / "sp500_constituents.json").write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    provenance = {
        "built_at": built_at,
        "primary_source": source,
        "cross_check_source": SPDJI_URL,
        "cross_check": cross_note,
        "count": len(snapshot["companies"]),
        "ranking": "market_cap_descending_at_snapshot_via_robinhood_fundamentals_batched_20_per_call",
        "market_cap_missing_tickers_ranked_last": missing_caps,
        "top5": snapshot["companies"][:5],
    }
    (REPO_ROOT / "data" / "sp500_provenance.json").write_text(
        json.dumps(provenance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"count": len(snapshot["companies"]),
                      "top5": [c["ticker"] for c in snapshot["companies"][:5]],
                      "missing_caps": missing_caps}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
