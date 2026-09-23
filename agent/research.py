"""Look something up on the web and leave the answer in a file.

The model in the chat box cannot reach the internet by itself -- aider has no
search tool, and a local model cannot call one mid-reply. So this runs
*between* runs instead: the model writes `RESEARCH: <question>` into its task
list, the Ralph loop notices, calls this, and the answer is sitting in
RESEARCH.md by the time the next run starts.

Also usable by hand when you want to hand it some reading:

    venv\\Scripts\\python.exe research.py --query "pygame per-pixel collision"
    venv\\Scripts\\python.exe research.py --url https://example.com/page

Search results are titles, links and snippets only. Pages are fetched in full
and trimmed, because a 32k context cannot afford more than a couple of them.
"""

import argparse
import hashlib
import json
import os
import sys
import time

try:
    import httpx
    from bs4 import BeautifulSoup
except ImportError:
    httpx = None
    BeautifulSoup = None

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) LocalCoder/1.0"
SEARCH_URL = "https://html.duckduckgo.com/html/"

# A whole page of HTML will not fit alongside the code in a small context.
PAGE_CHARS = 6000
SNIPPET_CHARS = 300

CACHE_DIR = ".localcoder-research-cache"
CACHE_TTL = 24 * 3600  # 24 hours


def _cache_path(key):
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return os.path.join(CACHE_DIR, digest)


def _cache_get(key):
    """Return cached data if fresh, else None."""
    try:
        with open(_cache_path(key), "r", encoding="utf-8") as f:
            entry = json.load(f)
        if time.time() - entry.get("ts", 0) < CACHE_TTL:
            return entry["data"]
    except (OSError, ValueError, KeyError):
        pass
    return None


def _cache_put(key, data):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(_cache_path(key), "w", encoding="utf-8") as f:
        json.dump({"ts": time.time(), "data": data}, f)


def search(query, limit=5):
    """Titles, URLs and snippets. No API key, no account."""
    cache_key = "search:%s:%d" % (query, limit)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    resp = httpx.post(
        SEARCH_URL,
        data={"q": query},
        headers={"User-Agent": UA},
        timeout=25,
        follow_redirects=True,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    hits = []
    for block in soup.select(".result")[: limit * 2]:
        link = block.select_one(".result__a")
        if not link:
            continue
        href = link.get("href", "")
        snippet_el = block.select_one(".result__snippet")
        snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""
        hits.append({
            "title": link.get_text(" ", strip=True),
            "url": href,
            "snippet": snippet[:SNIPPET_CHARS],
        })
        if len(hits) >= limit:
            break
    _cache_put(cache_key, hits)
    return hits


def fetch(url):
    """One page, stripped to readable text."""
    cache_key = "fetch:%s" % url
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    resp = httpx.get(url, headers={"User-Agent": UA}, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    body = soup.select_one("main") or soup.select_one("article") or soup.body or soup
    text = body.get_text("\n", strip=True)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    result = "\n".join(lines)[:PAGE_CHARS]
    _cache_put(cache_key, result)
    return result


def render(query, hits, pages):
    out = ["# Research: %s" % query,
           "",
           "*Looked up %s. Read this, use what helps, ignore the rest.*" % time.strftime("%Y-%m-%d %H:%M"),
           ""]
    if not hits:
        out += ["Nothing came back for that search.", ""]
    for i, hit in enumerate(hits, 1):
        out += ["## %d. %s" % (i, hit["title"]), "", hit["url"], ""]
        if hit["snippet"]:
            out += [hit["snippet"], ""]
    for url, text in pages:
        out += ["---", "", "## Full page: %s" % url, "", text, ""]
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description="Web lookup for LocalCoder.")
    parser.add_argument("--query", help="what to search for")
    parser.add_argument("--site", help="restrict search to one domain (e.g. python.org)")
    parser.add_argument("--url", action="append", default=[], help="a page to read in full (repeatable)")
    parser.add_argument("--out", default="RESEARCH.md", help="where to write the answer")
    parser.add_argument("--results", type=int, default=5, help="how many search hits to keep")
    parser.add_argument("--read-top", type=int, default=1,
                        help="also fetch this many of the top hits in full")
    args = parser.parse_args()

    if httpx is None or BeautifulSoup is None:
        print("httpx and beautifulsoup4 are missing. Run SETUP.bat.", file=sys.stderr)
        return 2
    if not args.query and not args.url:
        print("Give it --query or --url. Nothing to do otherwise.", file=sys.stderr)
        return 2

    hits = []
    if args.query:
        query = args.query
        if args.site:
            query = "site:%s %s" % (args.site, query)
        try:
            hits = search(query, args.results)
        except Exception as exc:
            print("Search failed: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)

    pages = []

    # Pages you asked for by hand are always attempted.
    for url in args.url:
        try:
            pages.append((url, fetch(url)))
        except Exception as exc:
            print("Could not read %s: %s" % (url, exc), file=sys.stderr)

    # Search hits are best-effort: plenty of sites answer a bare fetch with
    # 403, so work down the list until enough of them let us in.
    wanted = max(0, args.read_top)
    taken = 0
    for hit in hits:
        if taken >= wanted:
            break
        url = hit["url"]
        if not url or any(url == seen for seen, _ in pages):
            continue
        try:
            pages.append((url, fetch(url)))
            taken += 1
        except Exception as exc:
            print("Skipped %s: %s" % (url, str(exc).split("\n")[0][:80]), file=sys.stderr)

    if not hits and not pages:
        return 1

    body = render(args.query or "requested pages", hits, pages)
    out_path = os.path.abspath(args.out)
    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write(body)
    print("Wrote %s (%d hits, %d pages, %d chars)"
          % (out_path, len(hits), len(pages), len(body)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
