"""A local stand-in for <target>/w/api.php: tools that speak the MediaWiki API ask the cache instead of the server.

Only read actions that the cache can answer are served:
    wbgetentities     from the store (full documents), fetched with full_fetch when missing
    wbsearchentities  from the store, fetched with Cache.search when this exact search was never asked
Everything else gets an API error. The server listens on 127.0.0.1 only and handles one request at a time, so
the target sees the same pacing, budget and User-Agent as any other cache run.

    python -m wikibase_cache serve wikidata --port 8792 [--offline] [--max-requests N]
    GET http://127.0.0.1:8792/w/api.php?action=wbgetentities&ids=Q42&format=json
    GET http://127.0.0.1:8792/shutdown        ends the server and closes the run cleanly
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from .fetch import Cache

# wbgetentities props -> keys of the entity document; id and type are always kept
PROP_KEYS = {"labels": ("labels",), "descriptions": ("descriptions",), "aliases": ("aliases",),
             "claims": ("claims", "statements"), "sitelinks": ("sitelinks",),
             "info": ("pageid", "ns", "title", "lastrevid", "modified")}


def select_props(entity: dict, props: list[str]) -> dict:
    keys = {"id", "type"}
    for prop in props:
        keys.update(PROP_KEYS.get(prop, ()))
    return {k: v for k, v in entity.items() if k in keys}


def answer(cache: Cache, params: dict[str, str]) -> dict:
    action = params.get("action")
    if action == "wbgetentities":
        ids = [i for i in params.get("ids", "").split("|") if i]
        props = params.get("props", "info|sitelinks|aliases|labels|descriptions|claims|datatype").split("|")
        found = cache.full_fetch(ids)
        entities = {i: select_props(found[i], props) if i in found else {"id": i, "missing": ""} for i in ids}
        return {"entities": entities, "success": 1}
    if action == "wbsearchentities":
        return cache.search(params.get("search", ""), params.get("language", "en"), int(params.get("limit", 7)),
                            params.get("type", "item"))
    return {"error": {"code": "unsupported", "info": f"wikibase-cache serves wbgetentities and wbsearchentities, "
                                                     f"not {action!r}"}}


def serve(cache: Cache, port: int, log=print) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            url = urlparse(self.path)
            if url.path == "/shutdown":
                self._send({"shutdown": True})
                server.stopping = True
                return
            if not url.path.endswith("/api.php"):
                self.send_error(404)
                return
            params = {k: v[-1] for k, v in parse_qs(url.query).items()}
            try:
                body = answer(cache, params)
            except Exception as error:  # every failure goes back as an API error, the server keeps running
                body = {"error": {"code": "wikibase-cache", "info": f"{type(error).__name__}: {error}"}}
                log(f"{params.get('action')}: {body['error']['info']}")
            self._send(body)

        def _send(self, body: dict) -> None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args) -> None:
            pass

    server = HTTPServer(("127.0.0.1", port), Handler)
    server.stopping = False
    log(f"Serving {cache.target.name} on http://127.0.0.1:{port}/w/api.php"
        f"{' (offline)' if cache.offline else ''}; stop with GET /shutdown")
    try:
        while not server.stopping:
            server.handle_request()
    finally:
        server.server_close()
        log(f"Stopped: {cache.requests} requests to {cache.target.name}, {cache.fetched} entities fetched")
