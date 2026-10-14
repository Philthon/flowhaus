"""Connectors to outside apps. In this prototype they are dummies (no network calls)."""

from connectors._base import CALLS, ConnectorError, ItemError  # noqa: F401

CATALOG = [
    {"id": "clay", "name": "Clay", "category": "Enrichment", "auth": "api_key", "available": True,
     "description": "Look up companies and people: size, industry, job titles, LinkedIn.",
     "actions": ["enrich_company(domain_or_email)", "enrich_person(email)"]},
    {"id": "firecrawl", "name": "Firecrawl", "category": "Web", "auth": "api_key", "available": True,
     "description": "Read company websites and search the web.",
     "actions": ["scrape(url)", "search(query, limit)"]},
    {"id": "hubspot", "name": "HubSpot", "category": "CRM", "auth": "oauth", "available": False,
     "description": "Create and update contacts and deals."},
    {"id": "slack", "name": "Slack", "category": "Messaging", "auth": "oauth", "available": False,
     "description": "Post messages to channels."},
    {"id": "gmail", "name": "Gmail", "category": "Email", "auth": "oauth", "available": False,
     "description": "Read incoming emails and attachments."},
    {"id": "google_sheets", "name": "Google Sheets", "category": "Spreadsheets", "auth": "oauth", "available": False,
     "description": "Read and write rows in a sheet."},
]
