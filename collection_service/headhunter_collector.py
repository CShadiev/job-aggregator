"""Collector that scrapes job postings from the public hh.ru HTML pages."""

import asyncio
import json
import re
from datetime import datetime

from aiohttp import ClientSession, ClientTimeout
from bs4 import BeautifulSoup
from bs4.element import Tag

from config import Config, ConfigProvider
from logger_provider import LoggerProvider
from models.collection_service import CollectionResult, InvalidEntry, JobPosting
from monitoring.metrics import record_collector_entries_dropped

log = LoggerProvider.get_logger()

_SEARCH_URL = "https://hh.ru/search/vacancy"
_VACANCY_URL = "https://hh.ru/vacancy/{vacancy_id}"
_TIMEOUT = ClientTimeout(total=30)
_ACCEPT = "text/html,application/xhtml+xml"
_ACCEPT_LANGUAGE = "ru-RU,ru;q=0.9,en;q=0.8"
_VACANCY_CARD_CLASS = re.compile(r"^vacancy-card--")
_REMOTE_MARK = "удалённо"
_FULL_EMPLOYMENT = "Полная занятость"
_SOURCE = "headhunter"


class _FetchFailed(Exception):
    """A search or vacancy request failed; the whole run is discarded."""


class HeadHunterCollector:
    """Collect job postings from public hh.ru HTML pages.

    Downloads a search-results page, reads vacancy ids, then downloads each
    vacancy page. Requests run one at a time. Pagination stops on an empty
    search page, on the first posting at or older than ``min_date``, or after
    ``HH_MAX_PAGES`` search pages. A failed request discards the run so the
    checkpoint stays put.
    """

    def __init__(self, client: ClientSession | None = None):
        """Initialise the collector.

        Args:
            client: Optional pre-existing :class:`aiohttp.ClientSession`. A new
                session is created when this argument is omitted. Only a session
                created here is closed by :meth:`cleanup`.
        """
        self._owns_client = client is None
        self.client = client or ClientSession()
        self._needs_delay = False
        self._delay = 0.0
        self._headers: dict[str, str] = {}

    def get_source_name(self) -> str:
        """Return the unique identifier of the data source."""
        return _SOURCE

    async def collect_jobs(self, min_date: datetime | None = None) -> CollectionResult:
        """Collect job postings newer than *min_date* (``ICollector`` entry point).

        The page cap applies even when *min_date* is set. Postings stay in
        search order, which is newest-first.

        Args:
            min_date: Stop once a vacancy with ``posted_at <= min_date`` is
                reached. That vacancy is not included.

        Returns:
            Valid postings and vacancies whose essential fields could not be
            read. An empty result with no invalid entries means the run was
            discarded after a failed request, or the window had nothing new.
        """
        config = ConfigProvider.get_config()
        self._delay = config.HH_REQUEST_DELAY_SECONDS
        self._needs_delay = False
        self._headers = {
            "User-Agent": config.HH_USER_AGENT,
            "Accept": _ACCEPT,
            "Accept-Language": _ACCEPT_LANGUAGE,
        }
        log.info("Collecting jobs from HeadHunter", min_date=min_date)

        postings: list[JobPosting] = []
        invalid_entries: list[InvalidEntry] = []
        try:
            for page in range(config.HH_MAX_PAGES):
                html = await self._get(_SEARCH_URL, params=_search_params(config, page))
                vacancy_ids = _vacancy_ids(html)
                if not vacancy_ids:
                    break
                reached_checkpoint = False
                for vacancy_id in vacancy_ids:
                    vacancy_html = await self._get(_VACANCY_URL.format(vacancy_id=vacancy_id))
                    parsed = _parse_vacancy(vacancy_id, vacancy_html)
                    if isinstance(parsed, InvalidEntry):
                        invalid_entries.append(parsed)
                        continue
                    if min_date is not None and parsed.posted_at <= min_date:
                        reached_checkpoint = True
                        break
                    postings.append(parsed)
                if reached_checkpoint:
                    break
        except _FetchFailed:
            log.error(
                "HeadHunter collection discarded; checkpoint left unchanged",
                event="headhunter_collection_discarded",
            )
            return CollectionResult(postings=[], invalid_entries=[])

        log.info(
            "Collected {n} jobs from HeadHunter, dropped {dropped}",
            n=len(postings),
            dropped=len(invalid_entries),
        )
        record_collector_entries_dropped(
            source=_SOURCE,
            reason="parse",
            count=len(invalid_entries),
        )
        return CollectionResult(postings=postings, invalid_entries=invalid_entries)

    async def cleanup(self) -> None:
        """Close the HTTP session when this collector created it."""
        if self._owns_client:
            await self.client.close()

    async def _get(self, url: str, params: list[tuple[str, str]] | None = None) -> str:
        """Fetch one page. Sleep between requests, never before the first."""
        if self._needs_delay:
            await asyncio.sleep(self._delay)
        try:
            async with self.client.get(
                url,
                params=params,
                headers=self._headers,
                timeout=_TIMEOUT,
            ) as response:
                body = await response.text()
                if response.status < 200 or response.status >= 300:
                    log.error(
                        "HeadHunter request failed ({url}, status={status})",
                        url=url,
                        status=response.status,
                        event="headhunter_fetch_failed",
                    )
                    raise _FetchFailed
        except _FetchFailed:
            raise
        except Exception as exc:
            log.error(
                "HeadHunter request failed ({url}, {error})",
                url=url,
                error=str(exc),
                event="headhunter_fetch_failed",
            )
            raise _FetchFailed from exc
        self._needs_delay = True
        return body


def _search_params(config: Config, page: int) -> list[tuple[str, str]]:
    """Build the search query. Page 0 omits ``page``; later pages are 0-based."""
    params = [
        ("text", config.HH_TEXT),
        ("area", config.HH_AREA),
    ]
    params.extend(("experience", experience) for experience in config.HH_EXPERIENCE)
    params.extend(
        [
            ("employment_form", config.HH_EMPLOYMENT_FORM),
            ("label", config.HH_LABEL),
            ("search_period", str(config.HH_SEARCH_PERIOD)),
            ("accept_temporary", config.HH_ACCEPT_TEMPORARY),
            ("order_by", config.HH_ORDER_BY),
            ("ored_clusters", config.HH_ORED_CLUSTERS),
        ]
    )
    if page > 0:
        params.append(("page", str(page)))
    return params


def _vacancy_ids(html: str) -> list[str]:
    """Return vacancy ids from search-card ``id`` attributes, in page order."""
    soup = BeautifulSoup(html, "html.parser")
    ids: list[str] = []
    seen: set[str] = set()
    for element in soup.find_all(class_=_VACANCY_CARD_CLASS):
        if not isinstance(element, Tag):
            continue
        vacancy_id = element.get("id")
        if not isinstance(vacancy_id, str):
            continue
        vacancy_id = vacancy_id.strip()
        if not vacancy_id or vacancy_id in seen:
            continue
        seen.add(vacancy_id)
        ids.append(vacancy_id)
    return ids


def _parse_vacancy(vacancy_id: str, html: str) -> JobPosting | InvalidEntry:
    """Map one vacancy page onto a posting, or an invalid entry when unusable."""
    uid = f"{_SOURCE}:{vacancy_id}" if vacancy_id else ""
    if not vacancy_id:
        return InvalidEntry(entry={"uid": uid}, error="missing uid")

    soup = BeautifulSoup(html, "html.parser")
    ld = _json_ld_job_posting(soup)
    title = _plain(ld.get("title")) or _fallback_title(soup)
    company = _organization_name(ld) or _fallback_company(soup)
    description = _plain_html(ld.get("description")) or _fallback_description(soup)
    posted_at = _posted_at(ld.get("datePosted"))

    missing = [
        name
        for name, present in (
            ("title", bool(title)),
            ("company", bool(company)),
            ("description_raw", bool(description)),
            ("posted_at", posted_at is not None),
        )
        if not present
    ]
    if missing or posted_at is None:
        return InvalidEntry(entry={"uid": uid}, error="missing " + ", ".join(missing))

    employment = _qa_text(soup, "common-employment-text")
    return JobPosting(
        uid=uid,
        source=_SOURCE,
        title=title,
        company=company,
        location=_address_locality(ld) or _qa_text(soup, "vacancy-address-with-map"),
        remote=_REMOTE_MARK in _qa_text(soup, "work-formats-text"),
        url=_VACANCY_URL.format(vacancy_id=vacancy_id),
        tags=[],
        description_raw=description,
        job_types=["full"] if employment == _FULL_EMPLOYMENT else [],
        posted_at=posted_at,
        collected_at=datetime.now(),
    )


def _json_ld_job_posting(soup: BeautifulSoup) -> dict:
    """Return the JSON-LD ``JobPosting`` object, or an empty dict."""
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw or not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        found = _find_job_posting(data)
        if found is not None:
            return found
    return {}


def _find_job_posting(data: object) -> dict | None:
    """Walk a JSON-LD value until a ``JobPosting`` node appears."""
    if isinstance(data, list):
        for item in data:
            found = _find_job_posting(item)
            if found is not None:
                return found
        return None
    if not isinstance(data, dict):
        return None
    if _is_job_posting(data.get("@type")):
        return data
    graph = data.get("@graph")
    if isinstance(graph, list):
        return _find_job_posting(graph)
    return None


def _is_job_posting(kind: object) -> bool:
    if isinstance(kind, str):
        return kind == "JobPosting"
    if isinstance(kind, list):
        return "JobPosting" in kind
    return False


def _organization_name(ld: dict) -> str:
    org = ld.get("hiringOrganization")
    if isinstance(org, list):
        org = org[0] if org else None
    if isinstance(org, dict):
        return _plain(org.get("name"))
    return ""


def _address_locality(ld: dict) -> str:
    location = ld.get("jobLocation")
    if isinstance(location, list):
        location = location[0] if location else None
    if not isinstance(location, dict):
        return ""
    address = location.get("address")
    if isinstance(address, list):
        address = address[0] if address else None
    if not isinstance(address, dict):
        return ""
    return _plain(address.get("addressLocality"))


def _posted_at(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip())
    except ValueError:
        return None


def _plain(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _plain_html(value: object) -> str:
    """Reduce an HTML fragment to plain text. A blank result counts as missing."""
    html = _plain(value)
    if not html:
        return ""
    return BeautifulSoup(html, "html.parser").get_text(separator="\n", strip=True)


def _fallback_title(soup: BeautifulSoup) -> str:
    block = soup.find("div", class_="vacancy-title")
    if not isinstance(block, Tag):
        return ""
    heading = block.find("h1")
    if not isinstance(heading, Tag):
        return ""
    return heading.get_text(separator=" ", strip=True)


def _fallback_company(soup: BeautifulSoup) -> str:
    node = soup.find("span", class_="vacancy-company-name")
    if not isinstance(node, Tag):
        return ""
    return node.get_text(separator=" ", strip=True)


def _fallback_description(soup: BeautifulSoup) -> str:
    node = soup.find("div", class_="vacancy-description")
    if not isinstance(node, Tag):
        return ""
    return node.get_text(separator="\n", strip=True)


def _qa_text(soup: BeautifulSoup, qa: str) -> str:
    node = soup.select_one(f'[data-qa="{qa}"]')
    if not isinstance(node, Tag):
        return ""
    return node.get_text(separator=" ", strip=True)
