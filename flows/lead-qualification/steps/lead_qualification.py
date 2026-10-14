import pandas as pd
from hamilton.function_modifiers import tag

from connectors import clay, firecrawl
from flowkit import Skip, load_items, skip_where, update_items

PERSONAL_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.fr", "yahoo.co.uk", "hotmail.com",
    "outlook.com", "live.com", "icloud.com", "me.com", "aol.com", "gmx.de", "gmx.net",
    "web.de", "proton.me", "protonmail.com",
}
MIN_EMPLOYEES = 50
SENIOR_ENOUGH = {"Manager", "Director", "VP", "C-level"}


@tag(label="Get new leads", description="Gives you each new lead with name and email.", group="receive", app="Sample file")
def receive_leads(input_path: str) -> pd.DataFrame:
    return load_items(input_path)


@tag(
    label="Add company website",
    description="Adds the company domain and website from the email; skips invalid emails and personal addresses like Gmail.",
    group="receive",
    app="Code",
)
def find_company_website(receive_leads: pd.DataFrame) -> pd.DataFrame:
    def website(lead: dict) -> dict:
        email = str(lead.get("email", "")).strip().lower()
        if "@" not in email:
            raise Skip("No valid email address")
        domain = email.split("@", 1)[1]
        if domain in PERSONAL_EMAIL_DOMAINS:
            raise Skip("Personal email address, so no company website")
        return {"domain": domain, "website": f"https://{domain}"}

    return update_items(receive_leads, website)


@tag(
    label="Add what the company does",
    description="Adds what the company does, tech stack, pricing page and more from Firecrawl.",
    group="research",
    app="Firecrawl",
)
def read_company_website(find_company_website: pd.DataFrame) -> pd.DataFrame:
    def read(lead: dict) -> dict:
        page = firecrawl.scrape(lead["website"])
        return {
            "website_title": page.get("title"),
            "website_summary": page.get("summary"),
            "tech_stack": ", ".join(page.get("tech_stack") or []),
            "has_pricing_page": page.get("has_pricing_page"),
            "has_careers_page": page.get("has_careers_page"),
        }

    return update_items(find_company_website, read)


@tag(
    label="Add company details",
    description="Adds company name, company size, industry and more from Clay; skips companies whose size Clay doesn't know.",
    group="research",
    app="Clay",
)
def look_up_company(read_company_website: pd.DataFrame) -> pd.DataFrame:
    def enrich(lead: dict) -> dict:
        info = clay.enrich_company(lead["domain"])
        if info.get("employees") in (None, ""):
            raise Skip("Clay doesn't know the company size")
        return {
            "company": info.get("name"),
            "employees": int(info["employees"]),
            "industry": info.get("industry"),
            "location": info.get("location"),
            "company_linkedin": info.get("linkedin_url"),
        }

    return update_items(read_company_website, enrich)


@tag(
    label="Skip small companies",
    description="Skips companies with fewer than 50 employees.",
    group="qualify",
    app="Code",
)
def skip_small_companies(look_up_company: pd.DataFrame) -> pd.DataFrame:
    employees = pd.to_numeric(look_up_company["employees"], errors="coerce")
    return skip_where(look_up_company, employees < MIN_EMPLOYEES, "Fewer than 50 employees")


@tag(
    label="Add job title and seniority",
    description="Adds job title, seniority and LinkedIn profile from Clay; skips leads Clay can't find.",
    group="person",
    app="Clay",
)
def look_up_person(skip_small_companies: pd.DataFrame) -> pd.DataFrame:
    def enrich(lead: dict) -> dict:
        person = clay.enrich_person(lead["email"])
        return {
            "job_title": person.get("job_title"),
            "seniority": person.get("seniority"),
            "person_linkedin": person.get("linkedin_url"),
        }

    return update_items(skip_small_companies, enrich)


@tag(
    label="Keep managers and above",
    description="Skips leads below manager level, including those with unknown seniority.",
    group="person",
    app="Code",
)
def keep_managers_and_above(look_up_person: pd.DataFrame) -> pd.DataFrame:
    seniority = look_up_person["seniority"].fillna("").astype(str)
    too_junior = look_up_person["_rejected_reason"].isna() & ~seniority.isin(SENIOR_ENOUGH)
    return skip_where(look_up_person, too_junior, "Below manager level")
