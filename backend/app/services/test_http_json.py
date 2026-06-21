"""Self-check for safe HTTP JSON parsing."""

import json

import httpx

from app.services.http_json import parse_response_json


def _self_check() -> None:
    resp = httpx.Response(200, content=b"", request=httpx.Request("GET", "http://test"))
    assert parse_response_json(resp) is None

    resp = httpx.Response(200, content=b"<html>", request=httpx.Request("GET", "http://test"))
    assert parse_response_json(resp) is None

    resp = httpx.Response(200, content=json.dumps({"ok": True}).encode(), request=httpx.Request("GET", "http://test"))
    assert parse_response_json(resp) == {"ok": True}


if __name__ == "__main__":
    _self_check()
    print("http_json self-check OK")
