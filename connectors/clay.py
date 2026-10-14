"""Dummy Clay client: company and person enrichment.

Usage in a step:
    from connectors import clay
    info = clay.enrich_company("northwind.io")      # -> dict, see below
    person = clay.enrich_person("maya@northwind.io")  # -> dict

Raises connectors.ItemError when nothing is found for that input (skip the item),
and connectors.ConnectorError when Clay itself fails (the step fails).
"""

from __future__ import annotations

import random

from connectors._base import ConnectorError, ItemError, call, seed

APP, LABEL = "clay", "Clay"
FREE_MAIL = {"gmail.com", "outlook.com", "yahoo.com", "hotmail.com", "icloud.com", "gmx.de", "web.de"}
KNOWN = {
    "northwind.io": ("Northwind Logistics", 420, "Logistics", "Hamburg, DE"),
    "brightpath.health": ("Brightpath Health", 1200, "Healthcare", "Boston, US"),
    "kiteanalytics.com": ("Kite Analytics", 85, "Software", "London, UK"),
    "alpenrose.de": ("Alpenrose Foods", 310, "Food & Beverage", "Munich, DE"),
    "lumenlegal.co.uk": ("Lumen Legal", 40, "Legal", "Manchester, UK"),
    "orbitrobotics.ai": ("Orbit Robotics", 150, "Hardware", "Berlin, DE"),
    "sablefinance.com": ("Sable Finance", 2300, "Financial services", "New York, US"),
    "tidewater.studio": ("Tidewater Studio", 12, "Design", "Lisbon, PT"),
    "fernhill.edu": ("Fernhill Schools", 600, "Education", "Dublin, IE"),
    "quantaretail.com": ("Quanta Retail", 5000, "Retail", "Chicago, US"),
}
INDUSTRIES = ["Software", "Logistics", "Healthcare", "Retail", "Manufacturing", "Marketing", "Financial services", "Education"]
TITLES = [("Head of Operations", "Director"), ("VP Sales", "VP"), ("Founder & CEO", "C-level"), ("Marketing Manager", "Manager"),
          ("CTO", "C-level"), ("Office Manager", "Individual contributor"), ("RevOps Lead", "Manager"), ("Head of Growth", "Director"),
          ("Account Executive", "Individual contributor"), ("Student", "None")]


def _domain(value: str) -> str:
    value = (value or "").strip().lower()
    if "@" in value:
        value = value.split("@", 1)[1]
    for prefix in ("https://", "http://", "www."):
        value = value.removeprefix(prefix)
    return value.split("/")[0]


def enrich_company(domain_or_email: str) -> dict:
    """Company facts for a domain: name, employees, industry, location, linkedin_url, founded."""
    domain = _domain(domain_or_email)

    def run():
        if not domain or "." not in domain:
            raise ItemError(f"'{domain_or_email}' is not a company domain")
        if domain in FREE_MAIL:
            raise ItemError(f"{domain} is a personal email provider, so there is no company to look up")
        if "ratelimit" in domain:
            raise ConnectorError("Clay returned 429: rate limit reached (400 lookups per hour)")
        rng = random.Random(seed("company", domain))
        if domain in KNOWN:
            name, size, industry, location = KNOWN[domain]
        else:
            name = domain.split(".")[0].replace("-", " ").title()
            size = rng.choice([4, 11, 25, 48, 90, 180, 350, 900, 2500])
            industry = rng.choice(INDUSTRIES)
            location = rng.choice(["Berlin, DE", "Paris, FR", "Austin, US", "Toronto, CA", "Amsterdam, NL"])
        return {"domain": domain, "name": name, "employees": size, "industry": industry, "location": location,
                "linkedin_url": f"linkedin.com/company/{domain.split('.')[0]}", "founded": 1990 + rng.randint(0, 33)}

    return call(APP, LABEL, "enrich_company", {"domain": domain}, run, credits=2)


def enrich_person(email: str) -> dict:
    """Person facts for a work email: full_name, job_title, seniority, linkedin_url."""
    email = (email or "").strip().lower()

    def run():
        if "@" not in email:
            raise ItemError(f"'{email}' is not an email address")
        rng = random.Random(seed("person", email))
        if rng.random() < 0.12:
            raise ItemError(f"Clay found no person for {email}")
        title, seniority = rng.choice(TITLES)
        local = email.split("@")[0]
        return {"email": email, "full_name": local.replace(".", " ").replace("_", " ").title(), "job_title": title,
                "seniority": seniority, "linkedin_url": f"linkedin.com/in/{local.replace('.', '-')}"}

    return call(APP, LABEL, "enrich_person", {"email": email}, run, credits=3)
