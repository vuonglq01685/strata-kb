from strata_kb import httpio


def test_request_refuses_non_http_scheme():
    status, raw = httpio.request("GET", "file:///etc/passwd", {})
    assert status == 0
    assert b"refusing non-http(s) URL" in raw


def test_request_refuses_custom_scheme():
    status, raw = httpio.request("GET", "ftp://example.com/x", {})
    assert status == 0
    assert b"refusing non-http(s) URL" in raw


def test_request_returns_status_and_body_from_urlopen(monkeypatch):
    class _Resp:
        status = 204

        def read(self):
            return b"hi"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["method"] = req.get_method()
        seen["timeout"] = timeout
        return _Resp()

    monkeypatch.setattr(httpio.urllib.request, "urlopen", fake_urlopen)
    status, raw = httpio.request(
        "GET", "http://h:8321/api/health", {"X-A": "b"}, None, timeout=10
    )
    assert (status, raw) == (204, b"hi")
    assert seen == {
        "url": "http://h:8321/api/health",
        "method": "GET",
        "timeout": 10,
    }


def test_request_flattens_http_error_to_status_and_body(monkeypatch):
    import urllib.error

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 401, "Unauthorized", {}, None
        )

    monkeypatch.setattr(httpio.urllib.request, "urlopen", fake_urlopen)
    status, _raw = httpio.request("GET", "http://h:8321/api/docs", {})
    assert status == 401


def test_request_reports_connection_failure_as_status_zero(monkeypatch):
    import urllib.error

    def fake_urlopen(req, timeout=None):
        raise urllib.error.URLError("Connection refused")

    monkeypatch.setattr(httpio.urllib.request, "urlopen", fake_urlopen)
    status, raw = httpio.request("GET", "http://h:8321/api/health", {})
    assert status == 0
    assert b"Connection refused" in raw
