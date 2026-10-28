"""Bounded publisher-first PDF discovery with an audit trail for every attempt."""

import json
import http.client
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from .pdf import PDFError, inspect_pdf


class DownloadError(RuntimeError):
    pass


def public_url(url):
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}


class HTTP:
    def __init__(self, timeout=20, max_bytes=80 * 1024 * 1024):
        self.timeout = timeout
        self.max_bytes = max_bytes

    def get(self, url, accept="*/*", referer=None):
        for attempt in range(2):
            try:
                return self._get(url, accept, referer)
            except DownloadError as exc:
                if attempt or not str(exc).startswith("Network error"):
                    raise
                time.sleep(0.25)

    def _get(self, url, accept, referer):
        if not public_url(url):
            raise DownloadError("Not a public HTTP(S) source")
        headers = {"User-Agent": "AutoResearch/1.0", "Accept": accept, "Accept-Encoding": "identity"}
        if referer:
            headers["Referer"] = referer
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                content = response.read(self.max_bytes + 1)
                if len(content) > self.max_bytes:
                    raise DownloadError("Response exceeds the configured download size limit")
                return {"url": response.url, "content": content,
                        "content_type": response.headers.get("Content-Type", ""),
                        "charset": response.headers.get_content_charset() or "utf-8"}
        except urllib.error.HTTPError as exc:
            raise DownloadError(f"HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, http.client.HTTPException, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise DownloadError(f"Network error: {type(reason).__name__}: {reason}") from exc

    def json(self, url):
        try:
            return json.loads(self.get(url, "application/json")["content"])
        except (ValueError, UnicodeError) as exc:
            raise DownloadError("Metadata response is not JSON") from exc


class PDFLinks(HTMLParser):
    def __init__(self, url):
        super().__init__(convert_charrefs=True)
        self.base = url
        self.links = []
        self.anchor = None

    def add(self, url):
        url = urllib.parse.urljoin(self.base, url)
        if public_url(url) and url not in self.links:
            self.links.append(url)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and attrs.get("name", "").lower() in {"citation_pdf_url", "eprints.document_url", "citation_fulltext_html_url"}:
            if attrs.get("content"):
                self.add(attrs["content"])
        if tag == "link" and (attrs.get("type") == "application/pdf" or attrs.get("rel") == "canonical") and attrs.get("href"):
            self.add(attrs["href"])
        if tag == "a" and attrs.get("href"):
            self.anchor = attrs["href"]
            if ".pdf" in self.anchor.lower() or "pdf" in attrs.get("type", "").lower():
                self.add(self.anchor)
        # Publisher PDF viewer frames sometimes contain the actual file URL.
        if tag in {"iframe", "embed"} and attrs.get("src") and ".pdf" in attrs["src"].lower():
            self.add(attrs["src"])

    def handle_data(self, data):
        if self.anchor and ("pdf" in data.casefold() or "view on sciencedirect" in data.casefold()):
            self.add(self.anchor)

    def handle_endtag(self, tag):
        if tag == "a":
            self.anchor = None


class Downloader:
    def __init__(self, http=None, email=None, allow_repositories=False, max_sources=12):
        self.http = http or HTTP()
        self.email = email
        self.allow_repositories = allow_repositories
        self.max_sources = max_sources

    def metadata(self, doi):
        url = "https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="")
        return self.http.json(url)["message"]

    def acquire(self, record):
        doi = record["doi"]
        audit = []
        metadata = None
        if not doi:
            return {"state": "missing_doi", "reason": "No DOI in the input JSON", "attempts": audit}
        try:
            metadata = self.metadata(doi)
            if metadata.get("DOI", "").casefold() != doi.casefold():
                raise DownloadError("Crossref returned a different DOI")
        except (DownloadError, KeyError) as exc:
            audit.append({"source": "Crossref", "result": str(exc)})
            metadata = None
        queue = [("https://doi.org/" + urllib.parse.quote(doi, safe="/"), "doi_origin", None)]
        pdf_links = []
        if metadata:
            primary = metadata.get("resource", {}).get("primary", {}).get("URL")
            if primary:
                queue.append((primary, "publisher", None))
            for link in metadata.get("link", []):
                url = link.get("URL", "")
                path = urllib.parse.urlparse(url).path.lower().rstrip("/")
                if link.get("content-type") == "application/pdf" or path.endswith(("/pdf", ".pdf")):
                    pdf_links.append((url, "publisher", None))
        # Explicit links must have publisher/index evidence saved in the manifest.
        for link in record.get("publisher_pdf_links", []):
            if link.get("evidence_url") and public_url(link.get("url", "")):
                pdf_links.append((link["url"], "publisher", link["evidence_url"]))
        queue[0:0] = pdf_links
        if self.email:
            try:
                locations = self.http.json("https://api.unpaywall.org/v2/" + urllib.parse.quote(doi, safe="") +
                                           "?" + urllib.parse.urlencode({"email": self.email})).get("oa_locations", [])
                for location in locations:
                    source = location.get("host_type")
                    if source == "publisher" or self.allow_repositories:
                        for name in ("url_for_pdf", "url_for_landing_page"):
                            if location.get(name):
                                queue.append((location[name], source or "repository", None))
            except DownloadError as exc:
                audit.append({"source": "Unpaywall", "result": str(exc)})
        visited = set()
        titles = [record["title"]]
        if metadata:
            titles.extend(metadata.get("title", []))
        while queue and len(visited) < self.max_sources:
            url, source, referer = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            attempt = {"url": url, "source": source}
            audit.append(attempt)
            try:
                response = self.http.get(url, "application/pdf,text/html;q=0.9,*/*;q=0.5", referer)
                attempt["resolved_url"] = response["url"]
                content = response["content"]
                if content.lstrip().startswith(b"%PDF-"):
                    last_error = None
                    for title in titles:
                        try:
                            verification = inspect_pdf(content, title, doi)
                            attempt["result"] = "verified_pdf"
                            return {"state": "downloaded", "content": content, "metadata": metadata,
                                    "source_url": response["url"], "source_kind": source,
                                    "verification": verification, "attempts": audit}
                        except PDFError as exc:
                            last_error = exc
                    raise last_error
                if "html" in response["content_type"].lower() or b"<html" in content[:2048].lower():
                    html = content.decode(response["charset"], errors="replace")
                    if any(marker in html.casefold() for marker in ("akamai/interstitial", "_sec/verify", "cf-chl-")):
                        attempt["result"] = "Browser verification required; no verification challenge was automated"
                        continue
                    parser = PDFLinks(response["url"])
                    parser.feed(html)
                    queue[0:0] = [(link, source, response["url"]) for link in parser.links if link not in visited]
                    attempt["result"] = f"HTML page; {len(parser.links)} PDF candidates"
                else:
                    attempt["result"] = "Response is neither a PDF nor a publisher HTML page"
            except (DownloadError, PDFError, LookupError) as exc:
                attempt["result"] = str(exc)
        observations = list(dict.fromkeys(a["result"] for a in audit if a.get("result")))
        reason = "No verified accessible PDF found within the source limit"
        if observations:
            reason += "; " + "; ".join(observations)
        return {"state": "download_failed", "reason": reason,
                "metadata": metadata, "attempts": audit}
