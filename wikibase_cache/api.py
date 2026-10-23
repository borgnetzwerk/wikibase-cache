"""Read-only access to a Wikibase Action API, following API:Etiquette: one request at a time, maxlag, gzip,
backoff on overload, an informative User-Agent.

Whole responses are never stored or logged. Some instances echo the request headers, including credentials,
in the `debuginfo` part of every response; only entity documents leave this module.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from . import __version__
from .config import REPOSITORY_URL, REPO_ROOT, ConfigError, Operator, Target

RETRY_STATUS = (429, 502, 503, 504)
RETRY_API_CODES = ("maxlag", "ratelimited")
ENTITY_CONTENT_MODELS = {"wikibase-item": "item", "wikibase-property": "property", "wikibase-lexeme": "lexeme"}


class ApiError(Exception):
    pass


def commit_id(repo_root: Path = REPO_ROOT) -> str:
    """Short commit ID of the running code, read from .git without calling git; 'unknown' outside a clone."""
    git = repo_root / ".git"
    try:
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref: "):
            return head[:7]
        ref = head[5:]
        ref_file = git / ref
        if ref_file.exists():
            return ref_file.read_text(encoding="utf-8").strip()[:7]
        for line in (git / "packed-refs").read_text(encoding="utf-8").splitlines():
            if line.endswith(" " + ref):
                return line[:7]
    except OSError:
        pass
    return "unknown"


def user_agent(operator: Operator) -> str:
    """The operator is the client that makes the request; the tool and its library follow (Foundation User-Agent
    policy form: client with contact, then libraries)."""
    return (f"{operator.name} ({operator.contact}) wikibase-cache/{__version__}+{commit_id()} "
            f"({REPOSITORY_URL}) python-requests/{requests.__version__}")


class Api:
    def __init__(self, target: Target, operator: Operator, session: requests.Session | None = None,
                 sleep=time.sleep, log=print) -> None:
        self.target = target
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = user_agent(operator)
        self.sleep = sleep
        self.log = log
        self.requests = 0
        self._last_request = 0.0
        self._warned_php = False
        self.secrets: list[str] = []
        auth = target.auth
        if auth.method == "oauth2":
            token = auth.secret(auth.token_env)
            self.secrets.append(token)
            self.session.headers["Authorization"] = "Bearer " + token
        elif auth.method == "botpassword":
            self.secrets.append(auth.secret(auth.password_env))
        elif auth.method != "none":
            raise ConfigError(f"Unknown auth method {auth.method!r}")
        self._logged_in = auth.method != "botpassword"

    # ── Transport ──────────────────────────────────────────────────────────────

    def get(self, params: dict) -> dict:
        self._ensure_login()
        return self._call("GET", params)

    def _call(self, method: str, params: dict) -> dict:
        params = {**params, "format": "json", "formatversion": 2, "maxlag": self.target.maxlag}
        for attempt in range(self.target.retries + 1):
            self._pace()
            self.requests += 1
            try:
                if method == "GET":
                    response = self.session.get(self.target.api, params=params, timeout=self.target.timeout)
                else:
                    response = self.session.post(self.target.api, data=params, timeout=self.target.timeout)
            except (requests.ConnectionError, requests.Timeout) as error:
                if attempt < self.target.retries:
                    self._backoff(attempt, None, f"connection error ({type(error).__name__})")
                    continue
                raise ApiError(f"Connection failed: {type(error).__name__}") from None
            if response.status_code in RETRY_STATUS and attempt < self.target.retries:
                self._backoff(attempt, response.headers.get("Retry-After"), f"HTTP {response.status_code}")
                continue
            if response.status_code != 200:
                raise ApiError(f"HTTP {response.status_code} from {self.target.api}")
            data = self._parse(response)
            code = (data.get("error") or {}).get("code")
            if code in RETRY_API_CODES and attempt < self.target.retries:
                self._backoff(attempt, response.headers.get("Retry-After"), f"API {code}")
                continue
            if code:
                raise ApiError(f"API error {code}: {self.redact(str(data['error'].get('info')))}")
            return data
        raise ApiError("Retries exhausted")

    def _ensure_login(self) -> None:
        """Bot password (Special:BotPasswords): fetch a login token, then action=login; the session keeps the cookie."""
        if self._logged_in:
            return
        auth = self.target.auth
        token = self._call("GET", {"action": "query", "meta": "tokens", "type": "login"})["query"]["tokens"]["logintoken"]
        result = self._call("POST", {"action": "login", "lgname": auth.secret(auth.username_env),
                                     "lgpassword": auth.secret(auth.password_env), "lgtoken": token})
        status = (result.get("login") or {}).get("result")
        self._logged_in = status == "Success"
        if not self._logged_in:
            reason = self.redact(str((result.get("login") or {}).get("reason", "")))
            raise ApiError(f"Bot password login failed: {status} {reason}".strip())

    def _pace(self) -> None:
        wait = self.target.min_interval - (time.monotonic() - self._last_request)
        if self._last_request and wait > 0:
            self.sleep(wait)
        self._last_request = time.monotonic()

    def _backoff(self, attempt: int, retry_after: str | None, why: str) -> None:
        delay = int(retry_after) if retry_after and retry_after.isdigit() else self.target.backoff_base * 2 ** attempt
        self.log(f"  {why}, waiting {delay} s")
        self.sleep(delay)

    def _parse(self, response: requests.Response) -> dict:
        body = self._strip_php_notice(response.content)
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            snippet = self.redact(body[:200].decode("utf-8", errors="replace"))
            raise ApiError(f"No JSON in response (Content-Type {response.headers.get('Content-Type')}): "
                           f"{snippet!r}") from None

    def _strip_php_notice(self, body: bytes) -> bytes:
        """Cut off a block of PHP notices that starts with '<br />' and ends before the first line starting with
        '{' (a misconfigured server prints them in front of the JSON). Warns once per run."""
        if not body.startswith(b"<br />"):
            return body
        start = body.find(b"\n{")
        if start < 0:
            return body
        if not self._warned_php:
            notice = body[:start].decode("utf-8", errors="replace")
            for tag in ("<br />", "<b>", "</b>"):
                notice = notice.replace(tag, "")
            self.log("WARNING: server prints PHP notices in front of the response, cut off: "
                     + self.redact(" ".join(notice.split()))[:200])
            self._warned_php = True
        return body[start + 1:]

    def redact(self, text: str) -> str:
        for secret in self.secrets:
            text = text.replace(secret, "<secret>")
        return text

    # ── Calls ──────────────────────────────────────────────────────────────────

    def userinfo(self) -> dict:
        return self.get({"action": "query", "meta": "userinfo"})["query"]["userinfo"]

    def entity_namespaces(self) -> dict[str, int]:
        """Entity type -> namespace number, from the content model of each namespace (siteinfo)."""
        data = self.get({"action": "query", "meta": "siteinfo", "siprop": "namespaces"})
        namespaces = data["query"]["namespaces"]
        if isinstance(namespaces, dict):
            namespaces = list(namespaces.values())
        found = {}
        for namespace in namespaces:
            kind = ENTITY_CONTENT_MODELS.get(namespace.get("defaultcontentmodel"))
            if kind and kind not in found:
                found[kind] = namespace["id"]
        return found

    def list_revisions(self, namespace: int, cont: dict | None = None) -> tuple[dict[str, int], dict | None]:
        """One page of the listing: entity ID -> current revision ID, and the continuation (None at the end)."""
        params = {"action": "query", "generator": "allpages", "gapnamespace": namespace, "gaplimit": "max",
                  "prop": "info", **(cont or {})}
        data = self.get(params)
        pages = (data.get("query") or {}).get("pages") or []
        if isinstance(pages, dict):  # formatversion 1 shape, in case a server ignores formatversion=2
            pages = list(pages.values())
        listed = {page["title"].split(":", 1)[-1]: page["lastrevid"] for page in pages if "lastrevid" in page}
        return listed, data.get("continue")

    def entities(self, ids: list[str]) -> dict[str, dict]:
        """Entity documents for up to batch_size IDs (wbgetentities)."""
        return self.get({"action": "wbgetentities", "ids": "|".join(ids)})["entities"]
