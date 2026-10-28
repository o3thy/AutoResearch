"""Zotero 10 local API writes, stored attachments, and read-back verification."""

import hashlib
import http.client
import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from rr.extract import normalize_doi, title_key


class ZoteroError(RuntimeError):
    pass


class AuthorizationRequired(ZoteroError):
    pass


def new_key():
    return "".join(secrets.choice("23456789ABCDEFGHIJKLMNPQRSTUVWXYZ") for _ in range(8))


class ZoteroClient:
    def __init__(self, base="http://127.0.0.1:23119", auth_file=None, timeout=30, prompt_writes=False):
        parsed = urllib.parse.urlparse(base)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ZoteroError("The Zotero API base must be a local loopback HTTP address")
        self.base = base.rstrip("/")
        self.prefix = "/api/users/0"
        self.timeout = timeout
        self.prompt_writes = prompt_writes
        self.auth_file = Path(auth_file or Path(__file__).resolve().parents[1] / "zotero/.local/zotero-auth.json")
        self.server_id = None
        self.key = os.environ.get("RR_ZOTERO_LOCAL_KEY")
        self.remember = True
        self.probe()
        if not self.key and self.auth_file.exists():
            saved = json.loads(self.auth_file.read_text(encoding="utf-8"))
            if saved.get("server_id") == self.server_id:
                self.key = saved.get("key")
                self.remember = saved.get("remember", False)

    def request(self, method, path, data=None, headers=None, raw=False, authorize=False, timeout=None, reauthorized=False):
        request_headers = {"Zotero-API-Version": "3", **(headers or {})}
        if self.server_id:
            request_headers["Zotero-Server-ID"] = self.server_id
        if method != "GET" and not authorize:
            if not self.key:
                if self.prompt_writes:
                    self.authorize()
                else:
                    raise AuthorizationRequired("Zotero write permission required; run the authorize command and approve in Zotero")
            request_headers["Zotero-API-Key"] = self.key
        if data is not None and not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        request = urllib.request.Request(self.base + path, data=data, headers=request_headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                response_id = response.headers.get("Zotero-Server-ID")
                if self.server_id and response_id and response_id != self.server_id:
                    raise ZoteroError("Zotero database changed; stop and verify the target library")
                if not self.server_id:
                    self.server_id = response_id
                body = response.read()
                if method != "GET" and not authorize and not self.remember:
                    self.key = None
                    if self.auth_file.exists():
                        self.auth_file.unlink()
                if raw:
                    return body, dict(response.headers)
                return json.loads(body) if body else None
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                self.key = None
                if self.prompt_writes and not reauthorized:
                    self.authorize()
                    return self.request(method, path, data, headers, raw, authorize, timeout, reauthorized=True)
                raise AuthorizationRequired("Zotero authorization expired or was consumed; authorize again") from exc
            if authorize and exc.code == 403:
                raise AuthorizationRequired("Zotero write authorization was denied") from exc
            raise ZoteroError(f"Zotero API {method} {path.split('?')[0]} returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, http.client.HTTPException, OSError) as exc:
            raise ZoteroError("Zotero connection failed; check that Zotero is running") from exc

    def probe(self):
        _, headers = self.request("GET", "/api/", raw=True)
        if not self.server_id:
            raise ZoteroError("Zotero 10 with local write API support is required")
        return {"server_id": self.server_id, "version": headers.get("X-Zotero-Version"), "base_url": self.base}

    def authorize(self, timeout=600):
        response = self.request("POST", "/api/local/authorize", {"appName": "AutoResearch"},
                                authorize=True, timeout=timeout)
        if not response or not response.get("key"):
            raise AuthorizationRequired("No local API key was granted")
        self.key = response["key"]
        self.remember = response.get("remember", False)
        self.auth_file.parent.mkdir(parents=True, exist_ok=True)
        self.auth_file.write_text(json.dumps({"key": self.key, "server_id": self.server_id,
                                             "remember": self.remember}), encoding="utf-8")
        return {"authorized": True, "remembered": self.remember, "server_id": self.server_id}

    def get(self, suffix):
        return self.request("GET", self.prefix + suffix)

    def create(self, suffix, data):
        if data.get("key") and "version" not in data:
            data = {**data, "version": 0}
        response = self.request("POST", self.prefix + suffix, [data],
                                headers={"Zotero-Write-Token": uuid.uuid4().hex})
        failed = response.get("failed", {})
        if failed:
            raise ZoteroError("Zotero rejected object creation: " + str(failed.get("0", {}).get("message", failed)))
        created = response.get("successful", response.get("success", {})).get("0")
        key = created.get("key") if isinstance(created, dict) else created
        if not key:
            raise ZoteroError("Zotero did not acknowledge object creation")
        if data.get("key") and key != data["key"]:
            raise ZoteroError("Zotero saved an unexpected object key")
        return key

    def collections(self):
        return self.get("/collections")

    def collection(self, identifier):
        matches = [x for x in self.collections() if x["key"] == identifier or x["data"]["name"] == identifier]
        if len(matches) != 1:
            raise ZoteroError("Collection name/key is missing or ambiguous; use a unique collection key")
        return matches[0]

    def create_collection(self, name):
        matches = [x for x in self.collections() if x["data"]["name"] == name]
        if matches:
            if len(matches) != 1:
                raise ZoteroError("Multiple collections have this name; specify a collection key")
            return {"key": matches[0]["key"], "name": name, "created": False}
        key = self.create("/collections", {"key": new_key(), "name": name, "parentCollection": False})
        saved = self.get("/collections/" + key)
        return {"key": key, "name": saved["data"]["name"], "created": True}

    def item(self, key):
        return self.get("/items/" + key)

    def children(self, key):
        return self.get("/items/" + key + "/children")

    def find_paper(self, record, collection_key):
        search = record["doi"] or record["title"]
        items = self.get("/items?" + urllib.parse.urlencode({"q": search, "qmode": "everything", "itemType": "-attachment"}))
        matches = [x for x in items if x["data"]["itemType"] not in {"attachment", "note"} and
                   ((record["doi"] and normalize_doi(x["data"].get("DOI")) == record["doi"]) or
                    (not record["doi"] and collection_key in x["data"].get("collections", []) and
                     title_key(x["data"].get("title", "")) == title_key(record["title"])))]
        inside = [x for x in matches if collection_key in x["data"].get("collections", [])]
        if inside:
            matches = inside
        if len(matches) > 1:
            raise ZoteroError("Multiple existing Zotero records match this DOI; select/merge the intended record first")
        return matches[0] if matches else None

    def ensure_paper(self, record, collection_key):
        existing = None
        if record.get("item_key"):
            try:
                known = self.item(record["item_key"])
            except ZoteroError as exc:
                if "HTTP 404" not in str(exc):
                    raise
            else:
                data = known["data"]
                matches = (normalize_doi(data.get("DOI")) == record["doi"] if record["doi"] else
                           title_key(data.get("title", "")) == title_key(record["title"]))
                if not matches or data["itemType"] in {"attachment", "note"} or data.get("deleted"):
                    raise ZoteroError("Checkpoint item identity changed; verify the intended parent before continuing")
                existing = known
        if existing is None:
            existing = self.find_paper(record, collection_key)
        if existing:
            data = existing["data"]
            if collection_key not in data.get("collections", []):
                self.request("PATCH", self.prefix + "/items/" + existing["key"],
                             {"collections": [*data.get("collections", []), collection_key]},
                             headers={"If-Unmodified-Since-Version": str(existing["version"])})
            return existing["key"]
        metadata = record.get("metadata") or {}
        creators = [{"creatorType": "author", "firstName": author.get("given", ""), "lastName": author.get("family", "")}
                    for author in metadata.get("author", []) if author.get("family")]
        key = record.get("item_key") or new_key()
        record["item_key"] = key
        is_preprint = bool(record["doi"] and record["doi"].startswith("10.48550/arxiv."))
        is_conference = metadata.get("type") == "proceedings-article"
        item_type = "preprint" if is_preprint else "conferencePaper" if is_conference else "journalArticle"
        fields = {"key": key, "itemType": item_type, "title": (metadata.get("title") or [record["title"]])[0],
                  "DOI": record["doi"] or "", "creators": creators,
                  "url": "https://doi.org/" + record["doi"] if record["doi"] else "",
                  "collections": [collection_key], "tags": [{"tag": "AutoResearch"}],
                  "extra": "Source: AutoResearch; metadata from Crossref when available"}
        if is_preprint:
            fields["repository"] = "arXiv"
            fields["archiveID"] = record["doi"].split("arxiv.", 1)[1]
        elif is_conference:
            fields["proceedingsTitle"] = (metadata.get("container-title") or [record.get("journal") or ""])[0]
            fields["conferenceName"] = metadata.get("event", {}).get("name", "")
            fields["publisher"] = metadata.get("publisher", "")
        else:
            fields["publicationTitle"] = (metadata.get("container-title") or [record.get("journal") or ""])[0]
        date = metadata.get("published", {}).get("date-parts", [])
        if date:
            fields["date"] = "-".join(str(part) for part in date[0])
        elif record.get("year"):
            fields["date"] = str(record["year"])
        return self.create("/items", fields)

    def attachment_path(self, attachment_key):
        body, _ = self.request("GET", self.prefix + "/items/" + attachment_key + "/file/view/url", raw=True)
        parsed = urllib.parse.urlparse(body.decode().strip())
        if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
            raise ZoteroError("Attachment path is not a local file URI")
        return Path(urllib.request.url2pathname(parsed.path))

    def attach_pdf(self, parent_key, path, record, checkpoint):
        path = Path(path)
        content = path.read_bytes()
        md5 = hashlib.md5(content).hexdigest()
        for child in self.children(parent_key):
            data = child["data"]
            if data.get("contentType") == "application/pdf" and data.get("md5") == md5:
                stored = self.attachment_path(child["key"])
                if stored.is_file() and hashlib.sha256(stored.read_bytes()).digest() == hashlib.sha256(content).digest():
                    return {"key": child["key"], "path": str(stored), "already_present": True}
        attachment_key = record.get("attachment_key")
        if attachment_key:
            try:
                saved = self.item(attachment_key)
            except ZoteroError as exc:
                if "HTTP 404" not in str(exc):
                    raise
                saved = None
        else:
            saved = None
        if saved and saved["data"].get("parentItem") != parent_key:
            raise ZoteroError("Checkpoint attachment belongs to a different parent")
        if not saved:
            attachment_key = new_key()
            record["attachment_key"] = attachment_key
            checkpoint()
            self.create("/items", {"key": attachment_key, "itemType": "attachment", "parentItem": parent_key,
                                  "linkMode": "imported_file", "title": "Full Text PDF",
                                  "filename": path.name, "contentType": "application/pdf",
                                  "tags": [{"tag": "AutoResearch"}], "url": record.get("source_url") or ""})
        fields = {"md5": md5, "filename": path.name, "filesize": len(content),
                  "mtime": int(path.stat().st_mtime * 1000)}
        precondition = {"Content-Type": "application/x-www-form-urlencoded", "If-None-Match": "*"}
        upload = self.request("POST", self.prefix + "/items/" + attachment_key + "/file",
                              urllib.parse.urlencode(fields).encode(), headers=precondition)
        if not upload.get("exists"):
            parsed = urllib.parse.urlparse(upload["url"])
            expected = urllib.parse.urlparse(self.base)
            if parsed.scheme != expected.scheme or parsed.netloc != expected.netloc or not parsed.path.startswith("/api/local/uploads/"):
                raise ZoteroError("Refusing an attachment upload destination outside Zotero's local API")
            # The upload key authorizes phase two. Do not send the API key to it.
            request = urllib.request.Request(upload["url"], data=content,
                                             headers={"Content-Type": upload.get("contentType", "application/pdf")}, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    if response.status != 201:
                        raise ZoteroError("Zotero file upload was not acknowledged")
            except (urllib.error.URLError, TimeoutError, http.client.HTTPException, OSError) as exc:
                raise ZoteroError("Zotero attachment byte upload failed") from exc
            self.request("POST", self.prefix + "/items/" + attachment_key + "/file",
                         urllib.parse.urlencode({"upload": upload["uploadKey"]}).encode(), headers=precondition)
        stored = self.attachment_path(attachment_key)
        if not stored.is_file() or hashlib.sha256(stored.read_bytes()).digest() != hashlib.sha256(content).digest():
            raise ZoteroError("Stored attachment bytes did not match the source PDF")
        saved = self.item(attachment_key)
        if saved["data"].get("parentItem") != parent_key:
            raise ZoteroError("Attachment parent verification failed")
        return {"key": attachment_key, "path": str(stored), "already_present": False}
