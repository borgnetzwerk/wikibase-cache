"""An in-memory Wikibase Action API for offline tests. Like some real instances, it echoes the request headers
(including Authorization and Cookie) in debuginfo, and can put a PHP notice in front of the JSON body."""
from __future__ import annotations

import json


class FakeResponse:
    def __init__(self, status_code: int, payload, headers: dict | None = None, prefix: bytes = b"") -> None:
        self.status_code = status_code
        self.content = prefix + (json.dumps(payload).encode() if not isinstance(payload, bytes) else payload)
        self.headers = headers or {"Content-Type": "application/json"}


class FakeWiki:
    NAMESPACES = [{"id": 0, "name": ""}, {"id": 120, "name": "Item", "defaultcontentmodel": "wikibase-item"},
                  {"id": 122, "name": "Property", "defaultcontentmodel": "wikibase-property"}]

    def __init__(self, user: str = "ExampleBot", page_size: int = 3, php_notice: bool = False,
                 bot_login: tuple[str, str] | None = None) -> None:
        self.user = user
        self.page_size = page_size
        self.php_notice = php_notice
        self.bot_login = bot_login  # (lgname, lgpassword) the wiki accepts
        self.session_cookie: str | None = None
        self.entities: dict[str, dict] = {}
        self.calls: list[dict] = []
        self.fail_next: list[int] = []  # status codes to return before answering normally
        self.headers: dict = {}

    def put(self, entity_id: str, revision: int, label: str) -> None:
        self.entities[entity_id] = {"type": "item" if entity_id[0] == "Q" else "property", "id": entity_id,
                                    "lastrevid": revision, "labels": {"en": {"language": "en", "value": label}}}

    def link(self, entity_id: str, prop: str, target_id: str) -> None:
        """Add a claim entity_id --prop--> target_id."""
        statement = {"mainsnak": {"snaktype": "value", "property": prop,
                                  "datavalue": {"type": "wikibase-entityid", "value": {"id": target_id}}}}
        self.entities[entity_id].setdefault("claims", {}).setdefault(prop, []).append(statement)

    # requests.Session interface
    def get(self, url: str, params: dict, timeout: float, headers: dict | None = None) -> FakeResponse:
        if url.endswith("/sparql"):
            self.calls.append({"sparql": params["query"]})
            return FakeResponse(200, {"head": {"vars": ["x"]}, "results": {"bindings": [
                {"x": {"type": "literal", "value": f"answer to {params['query'][:20]}"}}]}})
        return self._respond(params)

    def post(self, url: str, data: dict, timeout: float) -> FakeResponse:
        return self._respond(data)

    def _respond(self, params: dict) -> FakeResponse:
        self.calls.append(dict(params))
        if self.fail_next:
            return FakeResponse(self.fail_next.pop(0), {"error": "overloaded"})
        payload = self._answer(params)
        payload["debuginfo"] = {"headers": {"Authorization": self.headers.get("Authorization", ""),
                                            "Cookie": self.session_cookie or ""},
                                "request": {k: str(v) for k, v in params.items()}}
        prefix = b"<br />\n<b>Notice</b>: key file permissions<br />\n" if self.php_notice else b""
        return FakeResponse(200, payload, prefix=prefix)

    def _logged_in(self) -> bool:
        return bool(self.headers.get("Authorization")) or self.session_cookie is not None

    def _answer(self, params: dict) -> dict:
        if params.get("meta") == "tokens":
            return {"query": {"tokens": {"logintoken": "login-token+\\"}}}
        if params.get("action") == "login":
            if self.bot_login and (params["lgname"], params["lgpassword"]) == self.bot_login:
                self.session_cookie = "session-cookie-value"
                return {"login": {"result": "Success", "lgusername": self.user}}
            return {"login": {"result": "Failed", "reason": "Incorrect username or password entered."}}
        if params.get("meta") == "userinfo":
            if not self._logged_in():
                return {"query": {"userinfo": {"id": 0, "name": "127.0.0.1", "anon": True}}}
            return {"query": {"userinfo": {"id": 1, "name": self.user}}}
        if params.get("meta") == "siteinfo":
            return {"query": {"namespaces": {str(n["id"]): n for n in self.NAMESPACES}}}
        if params.get("generator") == "allpages":
            letter = {120: "Q", 122: "P"}[params["gapnamespace"]]
            prefix = {120: "Item", 122: "Property"}[params["gapnamespace"]]
            ids = sorted((i for i in self.entities if i[0] == letter), key=lambda i: int(i[1:]))
            offset = int(params.get("gapcontinue", 0))
            chunk = ids[offset:offset + self.page_size]
            pages = [{"title": f"{prefix}:{i}", "lastrevid": self.entities[i]["lastrevid"]} for i in chunk]
            answer = {"query": {"pages": pages}}
            if offset + self.page_size < len(ids):
                answer["continue"] = {"gapcontinue": str(offset + self.page_size), "continue": "gapcontinue||"}
            return answer
        if params.get("action") == "wbgetentities":
            return {"entities": {i: self.entities.get(i, {"id": i, "missing": ""}) for i in params["ids"].split("|")}}
        return {"error": {"code": "badrequest", "info": "unknown"}}
