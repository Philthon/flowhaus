"""Dummy Firecrawl client: scrape a web page or search the web.

Usage in a step:
    from connectors import firecrawl
    page = firecrawl.scrape("https://northwind.io")   # -> dict, see below
    hits = firecrawl.search("northwind logistics pricing", limit=3)  # -> list of dicts

Raises connectors.ItemError when a page can't be read (skip the item),
and connectors.ConnectorError when Firecrawl itself fails (the step fails).
"""

from __future__ import annotations

import random

from connectors._base import ConnectorError, ItemError, call, seed
from connectors.clay import KNOWN

APP, LABEL = "firecrawl", "Firecrawl"
TAGLINES = ["Logistics software for growing fleets", "Healthcare scheduling made simple", "Analytics for modern teams",
            "Organic food, made in the Alps", "Legal services for startups", "Robots for small warehouses",
            "Banking infrastructure for fintechs", "A small, independent design studio", "Schools that grow with you",
            "Retail analytics at scale"]
TECH = ["HubSpot", "Salesforce", "Intercom", "Segment", "Stripe", "Shopify", "Webflow", "Zendesk", "Google Analytics"]


def _url(value: str) -> str:
    value = (value or "").strip()
    if "@" in value:
        value = value.split("@", 1)[1]
    if value and not value.startswith("http"):
        value = "https://" + value
    return value.rstrip("/")


def scrape(url: str) -> dict:
    """Read one page: url, title, description, word_count, has_pricing_page, has_careers_page, tech_stack, summary."""
    url = _url(url)

    def run():
        host = url.split("//", 1)[-1].split("/")[0]
        if not host or "." not in host:
            raise ItemError(f"'{url}' is not a web address")
        if host.endswith(("gmail.com", "outlook.com", "yahoo.com", "hotmail.com")):
            raise ItemError(f"{host} is an email provider, not a company website")
        if "down" in host:
            raise ConnectorError("Firecrawl is unavailable (503). Try again in a few minutes.")
        rng = random.Random(seed("scrape", host))
        if rng.random() < 0.1:
            raise ItemError(f"{url} returned 404 Not Found")
        bare = host.removeprefix("www.")
        if bare in KNOWN:  # same companies as the Clay dummy, so the two agree
            name, tagline = KNOWN[bare][0], TAGLINES[list(KNOWN).index(bare) % len(TAGLINES)]
        else:
            name, tagline = host.split(".")[0].replace("-", " ").title(), rng.choice(TAGLINES)
        return {"url": url, "title": f"{name} | {tagline}", "description": f"{name}: {tagline.lower()}.",
                "word_count": rng.randint(300, 4200), "has_pricing_page": rng.random() < 0.6,
                "has_careers_page": rng.random() < 0.5, "tech_stack": rng.sample(TECH, 3),
                "summary": f"{name} says it offers {tagline.lower()}. The site lists {rng.randint(2, 9)} customer logos"
                           f" and {'is hiring' if rng.random() < 0.5 else 'shows no open jobs'}."}

    return call(APP, LABEL, "scrape", {"url": url}, run, credits=1)


def search(query: str, limit: int = 3) -> list[dict]:
    """Web search: a list of {url, title, snippet}."""
    query = (query or "").strip()

    def run():
        if not query:
            raise ItemError("Empty search query")
        rng = random.Random(seed("search", query))
        words = [w for w in query.lower().split() if w.isalnum()] or ["result"]
        base = words[0]
        return [{"url": f"https://{base}{'' if i == 0 else f'-{w}'}.com", "title": f"{query.title()} – result {i + 1}",
                 "snippet": f"{rng.choice(TAGLINES)}. Mentions {' '.join(words[:3])}."}
                for i, w in enumerate(["", "blog", "news", "docs", "jobs"][:max(1, min(limit, 5))])]

    return call(APP, LABEL, "search", {"query": query, "limit": limit}, run, credits=1)
