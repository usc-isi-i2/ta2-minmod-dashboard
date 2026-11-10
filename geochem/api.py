"""GeoChem search API reads for the By-Product tab.

Filters use the API's `element` parameter (what samples measured), not
`commodity` (a site's declared inventory), with include_bdl=true so readings
below the detection limit count. Groups (PGE, REE) fan out to one request
per element and are merged here.
"""

from __future__ import annotations

import csv
import functools
import io
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from constants import GEOCHEM_API_ENDPOINT, GEOCHEM_ELEMENTS_CSV_URL, config
from logger_config import logger

# the largest deposit's samples are ~20 MB
TIMEOUT = 30
TIMEOUT_SAMPLES = 120

DETAIL_WORKERS = 8

_SESSION = requests.Session()


class GeochemAPIError(RuntimeError):
    """GeoChem API or element list failed; the message is safe to show users."""


def fetch(
    url: str,
    params: dict | None,
    timeout: int,
    service: str = "GeoChem data service",
) -> requests.Response:
    # messages are shown to viewers; server-side hints go to the log
    try:
        resp = _SESSION.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp
    except requests.exceptions.Timeout:
        raise GeochemAPIError(
            f"{service[0].upper()}{service[1:]} did not respond within {timeout}s. "
            "It may be under heavy load -- please try again."
        )
    except requests.exceptions.ConnectionError:
        logger.error(
            "Cannot reach %s -- check the dashboard server's network / ISI VPN", url
        )
        raise GeochemAPIError(f"{service[0].upper()}{service[1:]} is unreachable.")
    except requests.exceptions.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        logger.exception("HTTP %s from %s", status, url)
        raise GeochemAPIError(
            f"{service[0].upper()}{service[1:]} returned an error (HTTP {status})."
        )


def get_json(path: str, params: dict | None = None, timeout: int = TIMEOUT):
    """GET a GeoChem API path and return the parsed JSON."""
    resp = fetch(f"{GEOCHEM_API_ENDPOINT.rstrip('/')}/{path.lstrip('/')}", params, timeout)
    try:
        return resp.json()
    except ValueError:
        logger.exception("Malformed response from GeoChem API for %s", path)
        raise GeochemAPIError("The GeoChem data service returned an unreadable response.")


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------

_CACHE: dict = {}
_CACHE_LOCK = threading.Lock()
_MAX_ENTRIES = 512


def ttl_cache(ttl_seconds: int):
    """Thread-safe, per-process TTL memo. Errors are not cached.

    The call runs outside the lock so a slow request doesn't block other
    threads; concurrent misses may both fetch, which is harmless.
    """

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args):
            key = (fn.__name__, args)
            now = time.monotonic()

            with _CACHE_LOCK:
                entry = _CACHE.get(key)
                if entry is not None and now - entry[0] < ttl_seconds:
                    return entry[1]

            value = fn(*args)

            with _CACHE_LOCK:
                if len(_CACHE) >= _MAX_ENTRIES and key not in _CACHE:
                    # FIFO eviction
                    _CACHE.pop(next(iter(_CACHE)))
                _CACHE[key] = (time.monotonic(), value)
            return value

        return wrapper

    return decorator


def clear_cache() -> None:
    """Drop every cached result, e.g. after a fresh GeoChem load."""
    with _CACHE_LOCK:
        _CACHE.clear()


# --------------------------------------------------------------------------
# Value helpers
# --------------------------------------------------------------------------


def to_float(value) -> float | None:
    """Coerce a value to a float, or None if it isn't numeric."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def resolve_year(raw_year) -> int | None:
    """The paper's `year`, if plausible (currently always missing upstream)."""
    if raw_year is not None and str(raw_year).isdigit():
        year = int(raw_year)
        if 1900 <= year <= 2100:
            return year
    return None


def nulls_last(value: str | None) -> tuple:
    """Sort key putting missing values last."""
    return (value is None, value or "")


def uri_qid(uri: str | None) -> str | None:
    """'https://minmod.isi.edu/resource/Q1044' -> 'Q1044'."""
    return uri.rsplit("/", 1)[-1] if uri else None


# --------------------------------------------------------------------------
# Elements
# --------------------------------------------------------------------------


@ttl_cache(ttl_seconds=86400)
def elements_table() -> tuple[list[dict], dict[str, str]]:
    """The API's element rows and a lowercased symbol/name/alias -> symbol index."""
    resp = fetch(GEOCHEM_ELEMENTS_CSV_URL, None, TIMEOUT, service="the element list")
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    if not rows or not {"symbol", "name", "aliases"} <= set(rows[0]):
        logger.error("Unexpected element list format from %s", GEOCHEM_ELEMENTS_CSV_URL)
        raise GeochemAPIError("The element list could not be read.")

    index = {}
    for row in rows:
        for key in [row["symbol"], row["name"], *row["aliases"].split("|")]:
            if key:
                index[key.strip().lower()] = row["symbol"]
    return rows, index


def element_symbol(text: str | None) -> str | None:
    """The symbol for an element symbol, name or alias, any case."""
    if not text:
        return None
    return elements_table()[1].get(text.strip().lower())


def element_name(symbol: str) -> str:
    """'Ga' -> 'Gallium'; falls back to the symbol, since it is display-only."""
    try:
        rows = elements_table()[0]
    except GeochemAPIError:
        return symbol
    for row in rows:
        if row["symbol"] == symbol:
            return row["name"]
    return symbol


# By-Product adjustments to the shared critical minerals list
_CRITICAL_REMOVE = {"fluorspar", "graphite", "platinum"}
_CRITICAL_ADD = ["Carbon"]
_GROUP_ADD = {"PGE": ["Platinum", "Osmium"], "REE": ["Promethium"]}
# entries that are minerals, not elements
_MINERAL_TO_ELEMENT = {"barite": "Barium"}

GROUP_LABELS = {
    "PGE": "PGE (all platinum-group elements)",
    "REE": "REE (all rare-earth elements)",
}


def to_symbols(names) -> list[str]:
    """Element names -> symbols, de-duplicated; unknown names are skipped."""
    symbols = []
    for name in names:
        symbol = element_symbol(_MINERAL_TO_ELEMENT.get(name.strip().lower(), name))
        if symbol is None:
            logger.warning("No element symbol for critical mineral %r", name)
        elif symbol not in symbols:
            symbols.append(symbol)
    return symbols


def element_groups() -> dict[str, list[str]]:
    """{'PGE': [...], 'REE': [...]} as element symbols."""
    return {
        group: to_symbols([*config[group], *extra]) for group, extra in _GROUP_ADD.items()
    }


def expand(commodity: str) -> tuple[str, ...]:
    """The element symbols a dropdown value stands for: a group's members, or itself."""
    return tuple(element_groups().get(commodity, [commodity]))


def commodity_label(value: str) -> str:
    """'PGE' -> 'PGE', 'Ga' -> 'Gallium (Ga)'."""
    if value in GROUP_LABELS:
        return value
    return f"{element_name(value)} ({value})"


def get_commodities() -> list[dict]:
    """Dropdown options: the PGE and REE groups, then elements valued by symbol."""
    critical = [
        name for name in config["CRITICAL_MINERALS"] if name.lower() not in _CRITICAL_REMOVE
    ]
    groups = element_groups()
    symbols = set(to_symbols([*critical, *_CRITICAL_ADD]))
    for members in groups.values():
        symbols.update(members)

    elements = sorted(
        (
            {
                "label": commodity_label(symbol),
                "value": symbol,
                "search": f"{element_name(symbol)} {symbol}",
            }
            for symbol in symbols
        ),
        key=lambda o: o["label"],
    )
    return [
        {"label": GROUP_LABELS[group], "value": group, "search": GROUP_LABELS[group]}
        for group in groups
    ] + elements


# --------------------------------------------------------------------------
# Countries
# --------------------------------------------------------------------------


@ttl_cache(ttl_seconds=3600)
def get_country_names() -> dict[str, str]:
    """MinMod country id -> display name ('Q1044' -> 'China')."""
    return {uri_qid(c["uri"]): c["name"] for c in get_json("/countries")}


def country_name(candidate: dict) -> str | None:
    """Name for a country entry: from its MinMod id, else the observed value."""
    qid = uri_qid(candidate.get("normalized_uri"))
    return get_country_names().get(qid) or candidate.get("observed_name")


@ttl_cache(ttl_seconds=900)
def paper_detail(paper_id: str, element: str) -> dict:
    """/papers/{id} with only the sites that measured `element`."""
    return get_json(
        f"/papers/{paper_id}", {"element": element, "include_bdl": "true"}
    )


def get_countries(papers: list[dict]) -> list[dict]:
    """Dropdown options for the countries of the sites in `papers` (from get_papers).

    Values are MinMod ids, which the papers search accepts; labels are names.
    """
    pairs = [(p["paper_id"], e) for p in papers for e in p["elements"]]
    with ThreadPoolExecutor(DETAIL_WORKERS) as ex:
        details = list(ex.map(lambda pair: paper_detail(*pair), pairs))

    names = get_country_names()
    countries = {}
    for detail in details:
        for site in detail.get("sites", []):
            for c in (site.get("location_info") or {}).get("country", []):
                qid = uri_qid(c.get("normalized_uri"))
                if qid:
                    countries[qid] = names.get(qid, c.get("observed_name") or qid)
    return sorted(
        ({"label": name, "value": qid} for qid, name in countries.items()),
        key=lambda o: o["label"],
    )


# --------------------------------------------------------------------------
# Drill-down
# --------------------------------------------------------------------------


def get_papers(commodity: str, country: str | None = None) -> list[dict]:
    """Papers with a reading of `commodity` (a symbol or group), each listing
    the `elements` it matched. With `country`, a site in that country must
    have measured the element.
    """
    elements = expand(commodity)
    if len(elements) == 1:
        results = [papers_for_element(elements[0], country)]
    else:
        with ThreadPoolExecutor(DETAIL_WORKERS) as ex:
            results = list(ex.map(lambda e: papers_for_element(e, country), elements))

    papers = {}
    for element, element_papers in zip(elements, results):
        for p in element_papers:
            papers.setdefault(p["paper_id"], {**p, "elements": []})["elements"].append(element)

    papers = list(papers.values())
    papers.sort(
        key=lambda p: (p["year"] is None, -(p["year"] or 0), nulls_last(p["title"]))
    )
    return papers


def papers_for_element(element: str, country: str | None) -> list[dict]:
    """/papers for one element, reduced to the fields the grid shows."""
    params = {"element": element, "include_bdl": "true", "limit": 0}
    if country:
        params["country"] = country

    return [
        {
            "paper_id": p["paper_id"],
            "title": p.get("title"),
            "journal": p.get("journal"),
            "year": resolve_year(p.get("year")),
            "doi": p.get("doi"),
        }
        for p in get_json("/papers", params)
    ]


def get_deposits(paper_id: str, elements: list[str]) -> list[dict]:
    """Sites in `paper_id` that measured any of `elements`, each listing which."""
    sites = {}
    for element in elements:
        for site in paper_detail(paper_id, element).get("sites", []):
            sites.setdefault(site["id"], (site, []))[1].append(element)

    deposits = []
    for site, site_elements in sites.values():
        location = site.get("location_info") or {}
        countries = location.get("country") or []
        states = location.get("state_or_province") or []

        # keep the most confident deposit type candidate
        best_type = max(
            site.get("deposit_type_candidate") or [{}],
            key=lambda d: to_float(d.get("confidence")) or -1.0,
        )
        deposits.append(
            {
                "paper_id": paper_id,
                "site_id": site["id"],
                "deposit_name": site.get("name"),
                "country": country_name(countries[0]) if countries else None,
                "state": states[0].get("observed_name") if states else None,
                "deposit_type_text": best_type.get("observed_name"),
                "deposit_type_confidence": to_float(best_type.get("confidence")),
                "elements": site_elements,
            }
        )
    deposits.sort(key=lambda d: nulls_last(d["deposit_name"]))
    return deposits


@ttl_cache(ttl_seconds=900)
def get_samples(paper_id: str, site_id: str, elements: tuple[str, ...]) -> list[dict]:
    """One row per graded reading of `elements` on the site's samples.

    Fetches all samples unfiltered: the API's element filter drops samples
    whose readings are all zero. Keeps positive, below-detection (negative)
    and zero grades; drops blanks. Cached so the BDL switch only re-filters.
    """
    data = get_json(
        f"/papers/{paper_id}/samples",
        {"site_id": site_id, "limit": 0},
        timeout=TIMEOUT_SAMPLES,
    )

    samples = []
    for sample in data.get("items", []):
        if sample.get("is_deleted"):
            continue
        for ai, analysis in enumerate(sample.get("analyses") or []):
            if analysis.get("is_deleted"):
                continue
            for ei, reading in enumerate(analysis.get("elements") or []):
                if reading.get("is_deleted"):
                    continue
                symbol = element_symbol(reading.get("label"))
                if symbol not in elements:
                    continue
                grade = to_float(reading.get("grade"))
                if grade is None:
                    continue
                samples.append(
                    {
                        # no per-reading id in the API; position is unique
                        "measurement_id": f"{sample['id']}#{ai}#{ei}",
                        "sample_id": sample.get("sample_id"),
                        "sample_name": sample.get("sample_name"),
                        "mineral": sample.get("mineral"),
                        "analysis_id": analysis.get("analysis_id"),
                        "element": symbol,
                        "grade": grade,
                        "grade_unit": (reading.get("grade_unit") or {}).get("observed_name"),
                        "analytical_method": analysis.get("analytical_method"),
                    }
                )
    samples.sort(
        key=lambda s: (nulls_last(s["sample_name"]), nulls_last(s["analysis_id"]))
    )
    return samples


def detected_only(samples: list[dict]) -> list[dict]:
    """Rows with a detected grade (> 0), as a new list (`samples` may be cached)."""
    return [s for s in samples if s["grade"] > 0]


def common_unit(samples: list[dict]) -> str | None:
    """The grade unit shared by every row, or None if they differ."""
    units = {s.get("grade_unit") for s in samples}
    if len(units) == 1:
        return next(iter(units))
    return None


def summarize_grades(samples: list[dict], commodity: str) -> dict:
    """Min/max/avg/median of detected grades (> 0); negative means below detection."""
    grades = [s["grade"] for s in samples if s.get("grade") is not None and s["grade"] > 0]

    if not grades:
        return {
            "commodity": commodity,
            "count": 0,
            "min": None,
            "max": None,
            "avg": None,
            "median": None,
        }

    return {
        "commodity": commodity,
        "count": len(grades),
        "min": min(grades),
        "max": max(grades),
        "avg": statistics.mean(grades),
        "median": statistics.median(grades),
    }
