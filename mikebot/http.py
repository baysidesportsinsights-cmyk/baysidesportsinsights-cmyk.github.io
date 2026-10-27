"""Small HTTP helper with retries and a browser-like user agent."""

import json
import time
import urllib.error
import urllib.request

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)


class FetchError(Exception):
    pass


def fetch(url: str, *, retries: int = 2, timeout: int = 20) -> str:
    last = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                return resp.read().decode(charset, errors="replace")
        except urllib.error.HTTPError as e:
            # 4xx won't get better on retry
            if 400 <= e.code < 500:
                raise FetchError(f"{e.code} {url}") from e
            last = e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
        if attempt < retries:
            time.sleep(2 ** (attempt + 1))
    raise FetchError(f"{last} {url}")


def fetch_json(url: str, **kw):
    return json.loads(fetch(url, **kw))
