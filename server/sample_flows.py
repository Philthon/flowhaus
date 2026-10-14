"""Sample flows with generated run history, for validating the concept.

These flows have no real integrations: each step is a small Python function that
imitates what the app would do (Clay lookup, HubSpot create, Slack post, ...).
Runs are generated deterministically and produce exactly the same shapes as the
real runner (server/runs.py), so the UI treats sample and live flows the same.
"""

from __future__ import annotations

import random
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable

import pandas as pd

from server import maps, runs


class StepFailure(Exception):
    """The whole step failed (e.g. an API error), not just one item."""


@dataclass
class SampleStep:
    id: str
    label: str
    description: str
    group: str
    app: str
    fn: Callable[[dict, random.Random], dict]
    ms: tuple[int, int] = (80, 400)


@dataclass
class SampleFlow:
    id: str
    name: str
    description: str
    trigger: dict
    terms: dict
    title_field: str
    subtitle_field: str
    groups: list[dict]
    steps: list[SampleStep]
    make_items: Callable[[random.Random], list[dict]]
    run_times: Callable[[datetime], list[datetime]]
    failures: dict[int, tuple[str, str]] = field(default_factory=dict)  # run index -> (step id, message)
    next_run: str | None = None
    output: str = "Items that made it through"
    owner: str = "You"
    events: list[tuple[int, str, str]] = field(default_factory=list)  # (hours ago, level, text)


def _skip(item: dict, reason: str) -> dict:
    item["_rejected_reason"] = reason
    return item


# --------------------------------------------------------------------------- flow 1: lead enrichment

FIRST = ["Maya", "Jonas", "Lea", "Omar", "Sofia", "Ethan", "Aiko", "Lukas", "Nora", "Ravi", "Clara", "Mateo",
         "Hana", "Felix", "Zara", "Theo", "Ines", "Kwame", "Elif", "Noah"]
LAST = ["Berg", "Schulz", "Okafor", "Lindqvist", "Moreau", "Tanaka", "Silva", "Novak", "Fischer", "Haddad",
        "Kowalski", "Rossi", "Park", "Nguyen", "Weber", "Costa"]
COMPANIES = [("Northwind Logistics", "northwind.io", 420, "Logistics"), ("Brightpath Health", "brightpath.health", 1200, "Healthcare"),
             ("Kite Analytics", "kiteanalytics.com", 85, "Software"), ("Alpenrose Foods", "alpenrose.de", 310, "Food & Beverage"),
             ("Lumen Legal", "lumenlegal.co.uk", 40, "Legal"), ("Orbit Robotics", "orbitrobotics.ai", 150, "Hardware"),
             ("Sable Finance", "sablefinance.com", 2300, "Financial services"), ("Tidewater Studio", "tidewater.studio", 12, "Design"),
             ("Fernhill Schools", "fernhill.edu", 600, "Education"), ("Quanta Retail", "quantaretail.com", 5000, "Retail")]
FREE_MAIL = ["gmail.com", "outlook.com", "yahoo.com"]
TITLES = ["Head of Operations", "VP Sales", "Founder", "Marketing Manager", "CTO", "Office Manager", "Student",
          "RevOps Lead", "Head of Growth", "Freelancer"]


def lead_items(rng: random.Random) -> list[dict]:
    items = []
    for _ in range(rng.randint(4, 14)):
        first, last = rng.choice(FIRST), rng.choice(LAST)
        company = rng.choice(COMPANIES)
        free = rng.random() < 0.18
        domain = rng.choice(FREE_MAIL) if free else company[1]
        email = f"{first.lower()}.{last.lower()}@{domain}"
        if rng.random() < 0.15:
            email = f"  {email.upper()} "
        items.append({"name": f"{first} {last}", "email": email, "company": "" if free and rng.random() < 0.5 else company[0],
                      "message": rng.choice(["Pricing for 50 seats?", "Demo please", "Can you integrate with Salesforce?",
                                             "Just browsing", "Need a quote this week", "Student project"])})
    return items


def receive_submission(item, rng):
    item["email"] = item["email"].strip().lower()
    item["source"] = "Website form"
    return item


def find_company(item, rng):
    domain = item["email"].split("@")[-1]
    match = next((c for c in COMPANIES if c[1] == domain), None)
    if match:
        item["company"] = match[0]
        item["company_size"] = match[2]
        item["industry"] = match[3]
    else:
        item["company_size"] = None
        item["industry"] = None
    return item


def find_person(item, rng):
    item["job_title"] = rng.choice(TITLES)
    slug = item["name"].lower().replace(" ", "-")
    item["linkedin"] = f"linkedin.com/in/{slug}" if rng.random() < 0.8 else None
    return item


def score_lead(item, rng):
    score = 20
    if item.get("company_size"):
        score += min(40, item["company_size"] // 30)
    if item.get("job_title") in ("VP Sales", "Founder", "CTO", "Head of Operations", "RevOps Lead", "Head of Growth"):
        score += 30
    if any(w in item["message"].lower() for w in ("pricing", "quote", "demo", "seats")):
        score += 15
    score = max(5, min(98, score + rng.randint(-8, 8)))
    item["fit_score"] = score
    return item


def check_fit(item, rng):
    domain = item["email"].split("@")[-1]
    if domain in FREE_MAIL:
        return _skip(item, "Personal email address, so the company can't be checked")
    if item["fit_score"] < 50:
        return _skip(item, "Fit score is below the cut-off of 50")
    return item


def create_crm_contact(item, rng):
    item["hubspot_id"] = f"HS-{rng.randint(10000, 99999)}"
    return item


def notify_sales(item, rng):
    item["slack"] = "Posted in #sales-leads"
    return item


LEADS = SampleFlow(
    id="lead-enrichment",
    name="Inbound lead enrichment",
    description="Enriches new website leads with Clay, scores them and hands good ones to sales.",
    trigger={"type": "webhook", "label": "New Typeform submission", "app": "Typeform"},
    terms={"item": "lead", "items": "leads"},
    title_field="name", subtitle_field="email",
    groups=[
        {"id": "receive", "label": "Receive lead", "description": "Gives you the form answers with a cleaned-up email address.", "parent": None},
        {"id": "enrich", "label": "Add company and person details", "description": "Adds company size, industry, job title and LinkedIn from Clay.", "parent": None},
        {"id": "qualify", "label": "Score and filter leads", "description": "Adds a fit score (0-100) and skips personal emails and poor fits.", "parent": None},
        {"id": "handoff", "label": "Hand to sales", "description": "Creates each lead in HubSpot and posts it to #sales-leads.", "parent": None},
    ],
    steps=[
        SampleStep("receive_submission", "Receive form answers", "Gives you name, email, company and message from Typeform, with the email cleaned up.", "receive", "Typeform", receive_submission),
        SampleStep("find_company", "Add company details", "Adds company size and industry from Clay, based on the email domain.", "enrich", "Clay", find_company, (600, 2400)),
        SampleStep("find_person", "Add job title and LinkedIn", "Adds the person's job title and LinkedIn profile from Clay.", "enrich", "Clay", find_person, (500, 2000)),
        SampleStep("score_lead", "Add fit score", "Adds a 0-100 fit score from Claude, based on company size, role and message.", "qualify", "Claude", score_lead, (900, 3000)),
        SampleStep("check_fit", "Skip poor fits", "Skips personal email addresses and leads scoring below 50.", "qualify", "Code", check_fit, (5, 30)),
        SampleStep("create_crm_contact", "Create HubSpot contact", "Adds the HubSpot contact ID after creating or updating the contact.", "handoff", "HubSpot", create_crm_contact, (300, 900)),
        SampleStep("notify_sales", "Post to #sales-leads", "Posts a short summary of each lead to Slack.", "handoff", "Slack", notify_sales, (150, 500)),
    ],
    make_items=lead_items,
    run_times=lambda now: [now - timedelta(hours=h, minutes=(h * 37) % 60) for h in (1, 3, 5, 9, 14, 20, 26, 31, 40, 47, 55, 62, 70, 79, 91, 102, 118, 130, 151)],
    failures={4: ("find_company", "Clay returned 429: rate limit reached (400 lookups per hour). The flow will retry on the next lead, or raise the Clay plan limit.")},
    next_run="When the next form is submitted",
    output="Handed to sales (HubSpot contact + Slack message)",
    events=[(52, "change", "Claude raised the fit-score cut-off from 40 to 50 (you asked: “only send serious leads to sales”)"),
            (160, "change", "Flow turned on by you")],
)


# --------------------------------------------------------------------------- flow 2: churn digest

ACCOUNTS = ["Northwind Logistics", "Brightpath Health", "Kite Analytics", "Alpenrose Foods", "Lumen Legal", "Orbit Robotics",
            "Sable Finance", "Tidewater Studio", "Fernhill Schools", "Quanta Retail", "Pioneer Freight", "Mosaic Media",
            "Harbor Dental", "Evergreen Energy", "Atlas Insurance", "Juniper Hotels"]


def account_items(rng: random.Random) -> list[dict]:
    return [{"account": a, "plan": rng.choice(["Starter", "Team", "Business"]), "mrr_eur": rng.choice([290, 590, 1200, 2400, 4800])}
            for a in rng.sample(ACCOUNTS, rng.randint(10, 16))]


def fetch_subscriptions(item, rng):
    item["renews_in_days"] = rng.randint(5, 330)
    return item


def fetch_activity(item, rng):
    item["logins_30d"] = rng.randint(0, 400)
    item["logins_prev_30d"] = max(1, item["logins_30d"] + rng.randint(-120, 80))
    item["open_tickets"] = rng.choice([0, 0, 0, 1, 2, 4])
    return item


def compute_usage_drop(item, rng):
    change = round(100 * (item["logins_30d"] - item["logins_prev_30d"]) / item["logins_prev_30d"])
    item["usage_change_pct"] = change
    if change > -25 and item["open_tickets"] < 3:
        return _skip(item, "Usage is stable, no action needed")
    return item


def write_risk_summary(item, rng):
    reasons = []
    if item["usage_change_pct"] <= -25:
        reasons.append(f"logins down {abs(item['usage_change_pct'])}%")
    if item["open_tickets"] >= 3:
        reasons.append(f"{item['open_tickets']} open support tickets")
    item["summary"] = f"{item['account']}: " + " and ".join(reasons) + f"; renews in {item['renews_in_days']} days."
    return item


def post_digest(item, rng):
    item["slack"] = "In Monday digest (#customer-success)"
    return item


CHURN = SampleFlow(
    id="churn-digest",
    name="Weekly churn-risk digest",
    description="Every Monday, spots accounts that use the product less and sends a short summary to Customer Success.",
    trigger={"type": "schedule", "label": "Every Monday at 08:00", "app": "Schedule"},
    terms={"item": "account", "items": "accounts"},
    title_field="account", subtitle_field="plan",
    groups=[
        {"id": "collect", "label": "Add account data", "description": "Adds renewal dates from Stripe and logins and open tickets from HubSpot.", "parent": None},
        {"id": "assess", "label": "Find at-risk accounts", "description": "Adds the usage change and a one-line risk summary; skips stable accounts.", "parent": None},
        {"id": "deliver", "label": "Send digest", "description": "Posts all at-risk accounts in one message to #customer-success.", "parent": None},
    ],
    steps=[
        SampleStep("fetch_subscriptions", "Add renewal dates", "Adds days until renewal from Stripe.", "collect", "Stripe", fetch_subscriptions, (400, 1500)),
        SampleStep("fetch_activity", "Add usage and tickets", "Adds logins this month and last month, and open support tickets, from HubSpot.", "collect", "HubSpot", fetch_activity, (600, 1800)),
        SampleStep("compute_usage_drop", "Skip stable accounts", "Adds the change in usage (%) and skips accounts whose usage is stable.", "assess", "Code", compute_usage_drop, (5, 40)),
        SampleStep("write_risk_summary", "Add risk summary", "Adds a one-line explanation from Claude of why each account is at risk.", "assess", "Claude", write_risk_summary, (1200, 4000)),
        SampleStep("post_digest", "Post digest to Slack", "Posts one message listing all at-risk accounts in #customer-success.", "deliver", "Slack", post_digest, (200, 600)),
    ],
    make_items=account_items,
    run_times=lambda now: [(now - timedelta(days=(now.weekday()) + 7 * w)).replace(hour=8, minute=0, second=3) for w in range(0, 5)],
    failures={2: ("post_digest", "Slack said channel_not_found: #cs-alerts no longer exists. The channel was renamed to #customer-success.")},
    next_run="Next Monday at 08:00",
    output="Posted as one digest in #customer-success",
    events=[(24 * 12, "change", "Claude changed the Slack channel to #customer-success after the failed run")],
)


# --------------------------------------------------------------------------- flow 3: invoice booking

VENDORS = [("Hetzner Online", "Hosting"), ("WeWork", "Office"), ("Figma", "Software"), ("Lufthansa", "Travel"),
           ("Deutsche Telekom", "Phone"), ("Notion Labs", "Software"), ("Staples", "Office supplies")]


def invoice_items(rng: random.Random) -> list[dict]:
    items = []
    for _ in range(rng.randint(2, 7)):
        vendor, category = rng.choice(VENDORS)
        items.append({"file": f"{vendor.split()[0].lower()}_{rng.randint(1000, 9999)}.pdf", "from": f"billing@{vendor.split()[0].lower()}.com",
                      "vendor": vendor, "category": category})
    return items


def get_attachments(item, rng):
    item["received"] = "invoices@ inbox"
    return item


def extract_invoice_fields(item, rng):
    item["invoice_no"] = f"INV-{rng.randint(1000, 2999)}"
    net = rng.choice([49.0, 120.0, 310.5, 1204.0, 89.9, 2400.0])
    item["net_eur"] = net
    item["vat_eur"] = round(net * 0.19, 2)
    item["total_eur"] = round(net * 1.19 + (rng.choice([0, 0, 0, 0, 36.0])), 2)
    return item


def check_totals(item, rng):
    expected = round(item["net_eur"] + item["vat_eur"], 2)
    if abs(expected - item["total_eur"]) > 0.01:
        return _skip(item, "Total doesn't match net + VAT")
    return item


def check_duplicate(item, rng):
    if rng.random() < 0.12:
        return _skip(item, "Already booked last month")
    return item


def create_bill(item, rng):
    item["xero_bill"] = f"BILL-{rng.randint(300, 999)}"
    return item


def notify_finance(item, rng):
    item["slack"] = "Listed in #finance"
    return item


INVOICES = SampleFlow(
    id="invoice-booking",
    name="Invoice inbox to accounting",
    description="Reads PDF invoices sent to invoices@, checks them and books them as bills in Xero.",
    trigger={"type": "event", "label": "New email with a PDF in invoices@", "app": "Gmail"},
    terms={"item": "invoice", "items": "invoices"},
    title_field="vendor", subtitle_field="file",
    groups=[
        {"id": "receive", "label": "Receive invoices", "description": "Gives you each PDF attachment from the invoices@ inbox.", "parent": None},
        {"id": "read", "label": "Add invoice details", "description": "Adds invoice number, net amount, VAT and total from each PDF.", "parent": None},
        {"id": "check", "label": "Skip bad invoices", "description": "Skips invoices with wrong totals or that were already booked.", "parent": None},
        {"id": "book", "label": "Book in Xero", "description": "Creates a draft bill in Xero for each invoice and tells finance.", "parent": None},
    ],
    steps=[
        SampleStep("get_attachments", "Collect PDF attachments", "Gives you each attached PDF with its sender and vendor.", "receive", "Gmail", get_attachments, (300, 900)),
        SampleStep("extract_invoice_fields", "Add invoice details", "Adds invoice number, net amount, VAT and total, read from the PDF by Claude.", "read", "Claude", extract_invoice_fields, (1500, 5000)),
        SampleStep("check_totals", "Skip wrong totals", "Skips invoices where net + VAT doesn't equal the total.", "check", "Code", check_totals, (3, 20)),
        SampleStep("check_duplicate", "Skip already booked", "Skips invoices whose number was already booked in Xero.", "check", "Xero", check_duplicate, (200, 700)),
        SampleStep("create_bill", "Create Xero bill", "Adds the Xero bill number after creating a draft bill with the right category.", "book", "Xero", create_bill, (400, 1200)),
        SampleStep("notify_finance", "Tell finance", "Posts the booked bills to #finance.", "book", "Slack", notify_finance, (150, 400)),
    ],
    make_items=invoice_items,
    run_times=lambda now: [now - timedelta(hours=h) for h in (30, 44, 58, 75, 99, 120, 146)],
    failures={0: ("create_bill", "Xero said 401 Unauthorized: the connection expired. Reconnect Xero to continue.")},
    next_run="Paused",
    output="Booked as draft bills in Xero",
    events=[(29, "change", "Flow paused by you after the Xero connection expired")],
)

SAMPLE_FLOWS = {f.id: f for f in (LEADS, CHURN, INVOICES)}
ENABLED_BY_DEFAULT = {"lead-enrichment": True, "churn-digest": True, "invoice-booking": False}


# --------------------------------------------------------------------------- run generation


def _flow_steps(flow: SampleFlow) -> list[dict]:
    return [{"id": s.id, "label": s.label, "description": s.description, "group": s.group, "app": s.app,
             "file": None, "line": None, "inputs": []} for s in flow.steps]


def build_map(flow: SampleFlow) -> dict:
    steps = _flow_steps(flow)
    edges = [{"source": a.id, "target": b.id} for a, b in zip(flow.steps, flow.steps[1:])]
    return {"title": flow.name, "groups": flow.groups, "steps": steps, "edges": edges, "inputs": [],
            "levels": maps.build_levels(flow.groups, steps, edges),
            "problems": maps.validate(flow.groups, steps)}


def simulate_run(flow: SampleFlow, run_id: str, started: datetime, seed: int, fail: tuple[str, str] | None,
                 trigger: str) -> dict:
    rng = random.Random(seed)
    items = flow.make_items(rng)
    for i, item in enumerate(items, 1):
        item["_row_id"] = i
        item["_rejected_reason"] = None
    frame = pd.DataFrame(items)
    t = started
    nodes, frames, error = {}, {}, None
    steps = _flow_steps(flow)
    for step in flow.steps:
        node = runs._empty_node({"id": step.id, "label": step.label, "group": step.group})
        nodes[step.id] = node
        if error:
            continue
        before = frame.copy(deep=True)
        node["duration_ms"] = rng.randint(*step.ms) * max(1, len(items) // 4)
        stamp = t.isoformat(timespec="seconds")
        node["log"] = [{"t": stamp, "level": "info", "text": "Step started"}]
        if fail and fail[0] == step.id:
            node.update(runs.compare(before, None))
            node["status"] = "failed"
            node["error"] = {"message": fail[1], "type": "IntegrationError", "traceback": f"{step.app} API error\n{fail[1]}"}
            runs.add_step_log(node, stamp, error=fail[1])
            frames[step.id] = (before, None)
            error = {"node_id": step.id, "message": fail[1]}
            continue
        out = []
        for rec in before.to_dict(orient="records"):
            rec = {k: runs._clean(v) for k, v in rec.items()}
            out.append(rec if rec.get("_rejected_reason") else step.fn(dict(rec), rng))
        frame = pd.DataFrame(out)
        frames[step.id] = (before, frame)
        node.update(runs.compare(before, frame))
        node["status"] = "success"
        t += timedelta(milliseconds=node["duration_ms"])
        runs.add_step_log(node, t.isoformat(timespec="seconds"), items=flow.terms["items"])
    run = {"run_id": run_id, "flow_id": flow.id, "status": "failed" if error else "success",
           "started_at": started.isoformat(timespec="seconds"), "finished_at": t.isoformat(timespec="seconds"),
           "input_file": flow.trigger["label"], "trigger": trigger, "error": error, "nodes": nodes}
    run["groups"] = runs._group_results(frames, steps, flow.groups)
    run["input_items"], run["output_items"] = runs.io_items(frames, [s.id for s in flow.steps])
    if error:
        run["output_items"] = None
    run["contacts"] = runs._contact_trace(run, frames, [s.id for s in flow.steps], flow.title_field, flow.subtitle_field)
    run["summary"] = runs._summary(run)
    return run


_history: dict[str, list[dict]] = {}


def history(flow_id: str) -> list[dict]:
    """All runs of a sample flow, newest first (generated once per server start)."""
    if flow_id not in _history:
        flow = SAMPLE_FLOWS[flow_id]
        now = datetime.now().replace(microsecond=0)
        times = sorted((t for t in flow.run_times(now) if t <= now), reverse=True)
        generated = []
        for i, t in enumerate(times):
            run_id = f"{flow_id}-{t.strftime('%Y-%m-%dT%H-%M-%S')}"
            generated.append(simulate_run(flow, run_id, t, seed=zlib.crc32(f"{flow_id}-{i}".encode()), fail=flow.failures.get(i),
                                          trigger=flow.trigger["type"]))
        _history[flow_id] = generated
    return _history[flow_id]


def trigger_now(flow_id: str) -> dict:
    """'Run now' on a sample flow: simulate a fresh run and put it on top of the history."""
    flow = SAMPLE_FLOWS[flow_id]
    now = datetime.now().replace(microsecond=0)
    runs_ = history(flow_id)
    run = simulate_run(flow, f"{flow_id}-{now.strftime('%Y-%m-%dT%H-%M-%S')}-{len(runs_)}", now,
                       seed=int(now.timestamp()) & 0xFFFF, fail=None, trigger="manual")
    runs_.insert(0, run)
    return run
