"""Parse observed ResearchRabbit HTML without depending on generated class hashes."""

import re
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin


@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def text(self):
        return " ".join("".join(c if isinstance(c, str) else c.text() + " "
                                for c in self.children).split())

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()

    def has_class(self, prefix):
        return any(c.startswith(prefix) for c in self.attrs.get("class", "").split())

    def find(self, prefix):
        return next((n for n in self.walk() if n.has_class(prefix)), None)


class TreeParser(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
            "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("document")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self.stack[-1].tag not in {"script", "style"}:
            self.stack[-1].children.append(data)


def tree(html):
    parser = TreeParser()
    parser.feed(html)
    return parser.root


def normalize_doi(value):
    if not value:
        return None
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value.strip(), flags=re.I)
    return value.lower() if re.fullmatch(r"10\.\d{4,9}/\S+", value, re.I) else None


def title_key(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _text(node, prefix):
    child = node.find(prefix)
    return child.text() if child else None


def paper(title, nickname=None, journal=None, abstract=None, doi=None, url=None, authors=None):
    year = re.search(r"(?:,|\s)\s*((?:19|20)\d{2})\b", nickname or "")
    return {
        "title": title, "authors": authors or [], "year": int(year[1]) if year else None,
        "doi": normalize_doi(doi), "url": url, "abstract": None if abstract in
        {None, "", "(No abstract)", "No abstract"} else abstract,
        "journal": journal or None, "rr_author_label": nickname,
        "decision": "maybe", "relationship_type": None, "notes": None,
        "metadata_status": "unverified", "authors_complete": False,
    }


def parse_cards(html, page_url=None):
    root = tree(html)
    containers = [n for n in root.walk() if n.has_class("ListItemContainer-")]
    if not containers:
        containers = [n for n in root.walk() if n.has_class("ListItemArticleDetails__Container-")]
    results = []
    for container in containers:
        title = _text(container, "ListItemArticleDetails__Title-")
        if not title:
            continue
        link = next((n.attrs.get("href") for n in container.walk()
                     if n.tag == "a" and n.attrs.get("href")), None)
        doi = next((normalize_doi(n.attrs.get("href")) for n in container.walk()
                    if normalize_doi(n.attrs.get("href"))), None)
        results.append(paper(title, _text(container, "ListItemArticleDetails__Nickname-"),
                             _text(container, "ListItemArticleDetails__Journal-"),
                             _text(container, "ListItemArticleVerbose__Abstract-"), doi,
                             urljoin(page_url or "https://app.researchrabbit.ai/", link) if link else None))
    return results


def parse_detail(html, page_url=None):
    root = tree(html)
    title_node = root.find("ArticleTitle__Title-")
    if not title_node:
        return None
    # Restrict DOI/author extraction to the inspector rather than other result cards.
    scope = root.find("InspectorStyles__Content-") or root.find("ArticleDetailsDisplay__Container-") or root
    doi_match = re.search(r"\b10\.\d{4,9}/[^\s<>]+", scope.text(), re.I)
    links = [n.attrs["href"] for n in title_node.walk() if n.tag == "a" and n.attrs.get("href")]
    authors = [n.text() for n in scope.walk() if n.has_class("ArticleAuthors__AuthorButton-")]
    nickname = _text(scope, "ArticleDetailsDisplay__Nickname-")
    abstract_nodes = [n for n in scope.walk() if n.has_class("ArticleDetailsDisplay__AbstractParagraph-")]
    abstract = next((n.text() for n in abstract_nodes if not normalize_doi(n.text())), None)
    result = paper(title_node.text(), nickname, _text(scope, "ArticleDetailsDisplay__Journal-"),
                   abstract, doi=doi_match[0] if doi_match else None,
                   url=urljoin(page_url or "https://app.researchrabbit.ai/", links[0]) if links else None,
                   authors=authors)
    result["rr_url"] = page_url
    return result


def page_info(html):
    root = tree(html)
    text = root.text()
    match = re.search(r"\b(\d+)\s*[-\u2013]\s*(\d+)\s+of\s+(\d+)\b", text)
    paging = {"start": int(match[1]), "end": int(match[2]), "total": int(match[3])} if match else None
    has_password = any(n.tag == "input" and n.attrs.get("type") == "password" for n in root.walk())
    login = has_password or (not parse_cards(html) and bool(re.search(
        r"\b(?:sign in|log in|login)\b", text, re.I)) and not root.find("Navigation__LinkContainer-"))
    challenge = bool(re.search(r"verify you are human|complete the captcha|access denied", text, re.I))
    empty = bool(re.search(r"no (?:articles|results|papers) (?:found|available)|0\s*[-\u2013]\s*0\s+of\s+0", text, re.I))
    return {"pagination": paging, "login_required": login, "blocked": challenge, "empty": empty}


def deduplicate(papers):
    """Use DOI when present; merge exact normalized titles only if DOIs do not conflict."""
    result = []
    duplicates = []
    for incoming in papers:
        existing = next((p for p in result if
                         (incoming.get("doi") and p.get("doi") == incoming["doi"]) or
                         (title_key(p["title"]) == title_key(incoming["title"]) and
                          not (p.get("doi") and incoming.get("doi") and p["doi"] != incoming["doi"]))), None)
        if existing is None:
            result.append(dict(incoming))
            continue
        duplicates.append({"title": incoming["title"], "kept_title": existing["title"],
                           "doi": incoming.get("doi")})
        for key, value in incoming.items():
            if not existing.get(key) and value:
                existing[key] = value
        existing["provenance"] = list(dict.fromkeys(existing.get("provenance", []) + incoming.get("provenance", [])))
    return result, duplicates
