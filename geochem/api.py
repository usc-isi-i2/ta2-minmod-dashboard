"""GeoChem REST API reads backing the By-Product dashboard tab.

Every call goes to the GeoChem search API (ta2-table-understanding#21, with
the measured-element filter from #24). It is only served on dev, so the ISI
VPN must be reachable at request time, not just at build time.

The commodity filter is the API's `element` parameter, never `commodity`:
`commodity` matches each site's *declared* mineral inventory, while `element`
matches what the samples actually measured, which is what a by-product is.
Every element call passes include_bdl=true, so readings below the detection
limit (stored as negative grades) count as occurrences too.

The element list and the name <-> symbol mapping come from the API's own
elements.csv in ta2-minmod-kg, read at runtime rather than copied, so the
dropdown always resolves the same way the API does.
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

from constants import GEOCHEM_API_ENDPOINT, GEOCHEM_ELEMENTS_CSV_URL
from logger_config import logger

# List and detail calls answer in well under a second; samples for the
# heaviest deposit (Mount Isa) are ~20 MB and take ~3s.
TIMEOUT = 30
TIMEOUT_SAMPLES = 120

# Parallel /papers/{id} fetches when deriving the country list.
DETAIL_WORKERS = 8

_SESSION = requests.Session()


class GeochemAPIError(RuntimeError):
    """Raised when the GeoChem API (or the element list) is unreachable or errors.

    Carries a message that is safe to show to a dashboard user; the
    underlying traceback goes to the log instead.
    """


def _fetch(
    url: str,
    params: dict | None,
    timeout: int,
    service: str = "GeoChem data service",
) -> requests.Response:
    # Messages are shown to the person viewing the page, but it is the
    # dashboard server's connection that fails -- so they say what is wrong,
    # not what the viewer should do. Server-side hints go to the log.
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


def _get(path: str, params: dict | None = None, timeout: int = TIMEOUT):
    """GET a GeoChem API path and return the parsed JSON."""
    resp = _fetch(f"{GEOCHEM_API_ENDPOINT.rstrip('/')}/{path.lstrip('/')}", params, timeout)
    try:
        return resp.json()
    except ValueError:
        logger.exception("Malformed response from GeoChem API for %s", path)
        raise GeochemAPIError("The GeoChem data service returned an unreadable response.")


# --------------------------------------------------------------------------
# Cache
#
# The store only changes when a paper is ingested or a curator publishes an
# edit, so the TTLs are a safety valve against needing a restart, not a
# staleness guard.
# --------------------------------------------------------------------------

_CACHE: dict = {}
_CACHE_LOCK = threading.Lock()
_MAX_ENTRIES = 512


def _ttl_cache(ttl_seconds: int):
    """Tiny thread-safe TTL memo.

    The network call happens outside the lock on purpose: holding it across a
    slow request would serialise every Dash worker thread behind it. The cost
    is that two concurrent misses on the same key both hit the API, which is
    harmless for idempotent reads. Exceptions are not memoised, so a failed
    call is retried next time.

    Note the cache is per process, so a multi-worker gunicorn deployment pays
    one cold miss per worker.
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
                    # Crude FIFO eviction; dicts preserve insertion order.
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
    """Year of publication, read only from the paper's `year` field.

    The API leaves `year` out when it is empty, which is currently every
    paper -- ingestion drops it upstream -- so the Year column renders blank.
    That is intentional: the year is reported from the data or not at all,
    and this starts working on its own once ingestion is fixed.
    """
    if raw_year is not None and str(raw_year).isdigit():
        year = int(raw_year)
        if 1900 <= year <= 2100:
            return year
    return None


def _nulls_last(value: str | None) -> tuple:
    """Sort key putting missing values last."""
    return (value is None, value or "")


def _qid(uri: str | None) -> str | None:
    """'https://minmod.isi.edu/resource/Q1044' -> 'Q1044'."""
    return uri.rsplit("/", 1)[-1] if uri else None


# --------------------------------------------------------------------------
# Elements
# --------------------------------------------------------------------------


@_ttl_cache(ttl_seconds=86400)
def _elements() -> tuple[list[dict], dict[str, str]]:
    """The API's element table and its lookup index.

    Returns the rows ({symbol, name, aliases}) and a map from lowercased
    symbol, name or alias to symbol -- the same rule as the API's
    `element_symbol`, so `aluminium` and `Al` both resolve to `Al`.
    """
    resp = _fetch(GEOCHEM_ELEMENTS_CSV_URL, None, TIMEOUT, service="the element list")
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
    return _elements()[1].get(text.strip().lower())


def element_name(symbol: str) -> str:
    """Full element name for a symbol ('Ga' -> 'Gallium').

    Falls back to the symbol if it is unknown or the element list can't be
    loaded -- it is only used for display, so it must not fail a callback.
    """
    try:
        rows = _elements()[0]
    except GeochemAPIError:
        return symbol
    for row in rows:
        if row["symbol"] == symbol:
            return row["name"]
    return symbol


def get_commodities() -> list[dict]:
    """Dropdown options for every element, labelled by name, valued by symbol.

    `search` lets the dropdown match the symbol as well as the name.
    """
    return sorted(
        (
            {"label": row["name"], "value": row["symbol"], "search": f"{row['name']} {row['symbol']}"}
            for row in _elements()[0]
        ),
        key=lambda o: o["label"],
    )


# --------------------------------------------------------------------------
# Countries
# --------------------------------------------------------------------------


@_ttl_cache(ttl_seconds=3600)
def get_country_names() -> dict[str, str]:
    """MinMod country id -> display name ('Q1044' -> 'China')."""
    return {_qid(c["uri"]): c["name"] for c in _get("/countries")}


def _country_name(candidate: dict) -> str | None:
    """Display name for a location_info country entry.

    Uses the normalized MinMod id when there is one, else the raw observed
    value (an ISO-3 code in the GeoChem data).
    """
    qid = _qid(candidate.get("normalized_uri"))
    return get_country_names().get(qid) or candidate.get("observed_name")


@_ttl_cache(ttl_seconds=900)
def _paper_detail(paper_id: str, element: str) -> dict:
    """/papers/{id}, its sites filtered to those that measured `element`.

    Cached because the country list fetches it for every matching paper, and
    the Deposits step then reuses it.
    """
    return _get(
        f"/papers/{paper_id}", {"element": element, "include_bdl": "true"}
    )


@_ttl_cache(ttl_seconds=900)
def get_countries(element: str) -> list[dict]:
    """Dropdown options for the countries of sites that measured `element`.

    The API has no per-element country list, so this reads the sites of every
    matching paper, in parallel. Values are MinMod ids, which the papers
    search accepts as-is; labels are full names.
    """
    paper_ids = [p["paper_id"] for p in get_papers(element)]
    with ThreadPoolExecutor(DETAIL_WORKERS) as ex:
        details = list(ex.map(lambda pid: _paper_detail(pid, element), paper_ids))

    names = get_country_names()
    countries = {}
    for detail in details:
        for site in detail.get("sites", []):
            for c in (site.get("location_info") or {}).get("country", []):
                qid = _qid(c.get("normalized_uri"))
                if qid:
                    countries[qid] = names.get(qid, c.get("observed_name") or qid)
    return sorted(
        ({"label": name, "value": qid} for qid, name in countries.items()),
        key=lambda o: o["label"],
    )


# --------------------------------------------------------------------------
# Drill-down
# --------------------------------------------------------------------------


def get_papers(element: str, country: str | None = None) -> list[dict]:
    """Papers with a reading of `element` (detected or below detection limit).

    With `country`, the API requires one site to both be in that country and
    have measured the element.

    Not cached: the key space is (element x country) and each value grows
    with the store.
    """
    params = {"element": element, "include_bdl": "true", "limit": 0}
    if country:
        params["country"] = country

    papers = [
        {
            "paper_id": p["paper_id"],
            "title": p.get("title"),
            "journal": p.get("journal"),
            "year": resolve_year(p.get("year")),
            "doi": p.get("doi"),
        }
        for p in _get("/papers", params)
    ]
    papers.sort(
        key=lambda p: (p["year"] is None, -(p["year"] or 0), _nulls_last(p["title"]))
    )
    return papers


def get_deposits(paper_id: str, element: str) -> list[dict]:
    """Deposit sites in `paper_id` that measured `element`."""
    deposits = []
    for site in _paper_detail(paper_id, element).get("sites", []):
        location = site.get("location_info") or {}
        countries = location.get("country") or []
        states = location.get("state_or_province") or []

        # A site may carry several deposit_type_candidates -- competing
        # LLM-generated hypotheses. Keep the most confident one.
        best_type = max(
            site.get("deposit_type_candidate") or [{}],
            key=lambda d: to_float(d.get("confidence")) or -1.0,
        )
        deposits.append(
            {
                "paper_id": paper_id,
                "site_id": site["id"],
                "deposit_name": site.get("name"),
                "country": _country_name(countries[0]) if countries else None,
                "state": states[0].get("observed_name") if states else None,
                "deposit_type_text": best_type.get("observed_name"),
                "deposit_type_confidence": to_float(best_type.get("confidence")),
            }
        )
    deposits.sort(key=lambda d: _nulls_last(d["deposit_name"]))
    return deposits


@_ttl_cache(ttl_seconds=900)
def get_samples(paper_id: str, site_id: str, element: str) -> list[dict]:
    """Every graded reading of `element` on the samples of `site_id`.

    Fetches *all* the site's samples, with no element or include_bdl filter:
    grade filtering is done here, not by the API. The API's element filter
    never returns a sample whose only readings are zero, and include_bdl
    returns matching samples whole, so neither can express the tab's rules.
    The caller applies `detected_only` for the BDL switch.

    Returns positive, negative (below detection limit: "<0.4" is stored as
    -0.4) and zero grades. Blank grades (no value) are always dropped.

    The API returns whole samples (every element they measured), so this
    flattens sample -> analyses -> elements and keeps the selected element's
    readings. One row per reading, NOT aggregated: repeated spot analyses on
    one sample (e.g. 146 Ga spots) are real LA-ICP-MS data.

    Cached so that flipping the BDL switch only re-filters rows already held;
    the unfiltered response for a large site is ~28 MB.
    """
    data = _get(
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
                if reading.get("is_deleted") or element_symbol(reading.get("label")) != element:
                    continue
                grade = to_float(reading.get("grade"))
                if grade is None:
                    continue
                samples.append(
                    {
                        # The API has no per-reading id. The position within
                        # this response is unique, which is all AgGrid's
                        # getRowId needs.
                        "measurement_id": f"{sample['id']}#{ai}#{ei}",
                        "sample_id": sample.get("sample_id"),
                        "sample_name": sample.get("sample_name"),
                        "mineral": sample.get("mineral"),
                        "analysis_id": analysis.get("analysis_id"),
                        "grade": grade,
                        "grade_unit": (reading.get("grade_unit") or {}).get("observed_name"),
                        "analytical_method": analysis.get("analytical_method"),
                    }
                )
    samples.sort(
        key=lambda s: (_nulls_last(s["sample_name"]), _nulls_last(s["analysis_id"]))
    )
    return samples


def detected_only(samples: list[dict]) -> list[dict]:
    """The rows with a detected grade (> 0): no zero or below-detection values.

    Returns a new list; `samples` may be a cached value and is not modified.
    """
    return [s for s in samples if s["grade"] > 0]


def common_unit(samples: list[dict]) -> str | None:
    """The grade unit shared by every row, or None if they differ or any is missing.

    Units are read from each reading's grade_unit; every reading in the store
    is ppm today, but nothing guarantees it for future papers.
    """
    units = {s.get("grade_unit") for s in samples}
    if len(units) == 1:
        return next(iter(units))
    return None


def summarize_grades(samples: list[dict], commodity: str) -> dict:
    """Min/max/avg/median of the detected grades of `commodity` over `samples`.

    Only grades > 0 count. A negative grade encodes a reading below the
    detection limit ("<0.4" is stored as -0.4) and a zero or missing grade is
    no measurement, so including them would drag the statistics down -- even
    below zero. The grid still shows every reading.
    """
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
