from __future__ import annotations
import logging
logger = logging.getLogger(__name__)
# 🚀 ApplyPilot Ultra — Advanced Sales Engineer / Solutions Consultant Scraper
# - Rich logs, --loose / --strict switches, robust scoring, safe email batching
# - Email body now shows provider counts + the exact CLI flags used


import argparse, csv, json, re, os, smtplib, time, logging
from pathlib import Path
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

import httpx
import sys
from dotenv import load_dotenv
from dateutil import parser as dtparse
from rich.console import Console
from rich.table import Table

# --- NO_ARCHITECT early guard (must be before any defs) ---
try:
    NO_ARCHITECT  # noqa: F401
except NameError:
    NO_ARCHITECT = False
import os, sys  # ensure available here
try:
    if os.getenv("NO_ARCHITECT","").strip().lower() in ("1","true","yes","y"):
        NO_ARCHITECT = True
    if "--no-architect" in sys.argv:
        NO_ARCHITECT = True
        try:
            sys.argv.remove("--no-architect")
        except ValueError:
            pass
except Exception:
    pass
# --- end guard ---

try:
    from rich.logging import RichHandler
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[RichHandler()])
except Exception:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

log = logging.getLogger("applypilot")
load_dotenv()

ROLE_FAMILY = "Sales Engineer / Solutions Consultant / Technical Sales"
USER_AGENT   = "ApplyPilot-Ultra-Scraper/2.0 (+personal-use)"
REQUEST_TIMEOUT = 45

# ===================== Title logic (widened but safe) =====================
TITLE_KEEP_RE = re.compile(
    r"""(?ix)\b(
        sales\s*engineer(?:ing)?|
        solutions?\s*(engineer(?:ing)?|consultant|architect)|
        (?:pre[-\s]?sales|presales)\s*engineer|
        technical\s*(account\s*manager|sales\s*engineer)|
        (customer|partner|field)\s*(engineer|solutions?)|
        implementation\s*(specialist|engineer|consultant)|
        (?:field\s+)?applications?\s*engineer|
        customer\s*engineer|
        (?:solution|technical)\s*consultant|
        demo\s*engineer|
        value\s*engineer
    )\b"""
)

TITLE_SYSTEMS_RE = re.compile(r"(?i)\bsystems?\s*engineer\b")
TITLE_SALESY_NEARBY_RE = re.compile(r"(?i)\b(sales|pre[-\s]?sales|presales|solutions?|demo|poc|proof\s*of\s*concept|rfi|rfp|technical\s*account)\b")

TITLE_HARDDROP = re.compile(r"(?i)\b(head of|^head\b|regional manager|manager|management|mgr)\b")
# Hard drops to avoid pure ops/dev roles & non-tech-sales
TITLE_DROP_RE = re.compile(
    r"""(?ix)\b(
        account\s+executive|account\s+manager|devops|sre|help\s*desk|desktop\s*support|
        support\s*technician|field\s*service|maintenance|hvac|biomedical|
        analog|rf|pcb|semiconductor|solidworks|network\s+engineer|
        systems?\s+administrator|security\s+operations|infrastructure\s+engineer|
        data\s+(scientist|analyst)|project\s+manager|scrum\s+master|product\s+(manager|owner)|
        frontend|back\s*end|full\s*stack|mobile\s+developer|game\s+developer|graphic\s+designer|
        ui/ux\s+designer|marketing|recruiter|talent\s+acquisition|warehouse|logistics
    )\b"""
)

# Seniority rules (default: avoid heavy senior unless explicitly jr/mid)
SENIORITY_EXCLUDE = re.compile(r"(?i)\b(staff|principal|lead|head|director|vp|vice\s*president|chief|senior|sr\.?|manager|management|mgr)\b")
SENIORITY_INCLUDE_HINTS = re.compile(r"(?i)\b(associate|jr|junior|mid|ii|iii|intermediate|entry|graduate|grad)\b")

# ===================== Body signals =====================
INCLUDE_SIGNALS = [
    # presales motions
    "discovery","requirements","poc","proof of concept","pilot","demo","solution design",
    "architecture","rfi","rfp","scoping","sow","enablement","stakeholders","sales cycle",
    "ae","account executive","objections","value","roi",
    # tech
    "api","webhook","integration","rest","graphql","sdk","cli","postman","curl",
    "oauth","saml","sso","jwt","linux","python","sql","etl","aws","azure","gcp","docker","kubernetes",
    # docs/diagrams
    "documentation","rfp responses","sequence diagram","architecture diagram","runbook"
]
EXCLUDE_SIGNALS = [
    "ticket queue","pager duty","on-call rotation","incident response","sla restore","patching",
    "backup","rack","cabling","repair","troubleshoot hardware onsite","install equipment",
    "no remote","onsite only","5 days onsite","help desk","service desk","desktop support"
]

CLEARANCE_RE = re.compile(r"(?i)\b(US citizens? only|must be a US citizen|ts/?sci|public trust|nv1|nv2|bpss|baseline)\b")

# ===================== Geography & defaults =====================
COUNTRY_ALIASES = {
    "usa":"United States","us":"United States","u.s.":"United States",
    "australia":"Australia","au":"Australia",
    "anywhere":"Anywhere","remote":"Anywhere","worldwide":"Worldwide","global":"Global",
    "eu":"Europe","emea":"EMEA","apac":"APAC","latam":"LATAM",
}
DEFAULT_INCLUDE = (
    "United States,Australia,New Zealand,Canada,United Kingdom,Europe,EU,EMEA,APAC,Remote,Anywhere,Worldwide,Global,"
    "Latin America,LATAM,South America,North America,Africa,Asia,Middle East"
)

DEFAULT_KEYWORDS = [
    "sales engineer","solutions engineer","solutions consultant","pre-sales","presales",
    "technical sales engineer","technical account manager","customer engineer",
    "implementation engineer","field applications engineer","solutions architect","value engineer"
]

EMAIL_SUBJECT_PREFIX = os.getenv("EMAIL_SUBJECT_PREFIX", "[ApplyPilot]")
EMAIL_BASE_SUBJECT   = os.getenv("EMAIL_SUBJECT", "SE/SC Job Digest (Ultra)")
EMAIL_LABEL          = os.getenv("EMAIL_LABEL", "SE-Digest")

# ===================== Providers (stable sync HTTPX) =====================
GREENHOUSE_COMPANIES = [
    "atlassian","canva","xero","airwallex","cultureamp","zapier","automattic","gitlab","doist",
    "linearapp","mongodb","datadog","notion","figma","dropbox","sentry","mozilla","paddle",
    "wise","shopify","klarna"
]
LEVER_COMPANIES = [
    "loom","retool","samsara","rippling","brex","opendoor","angellist","airtable","robinhood","scaleai","benchling"
]

@dataclass
class Job:
    @staticmethod
    def fetch_smartrecruiters_jobs(lines):
        try:
            slugs = [ln for ln in lines if ln and not ln.startswith('#')]
        except Exception:
            slugs = []
        if not slugs:
            return []
        headers = {"User-Agent": USER_AGENT}
        client = httpx.Client(headers=headers, timeout=REQUEST_TIMEOUT)
        jobs = []
        for slug in slugs:
            url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100"
            try:
                r = client.get(url)
                if r.status_code != 200:
                    logger.debug(f"[smartrecruiters] {slug} -> {r.status_code}")
                    continue
                data = r.json()
                for item in data.get('content', []):
                    title = (item.get('name') or '').strip()
                    ref = item.get('ref', {}) or {}
                    link = ref.get('jobAdUrl') or ref.get('uri') or f"https://www.smartrecruiters.com/{slug}/{item.get('id','')}"
                    dstr = item.get('releasedDate') or item.get('createdOn')
                    posted_at = None
                    if dstr:
                        try:
                            posted_at = dtparse.parse(dstr).date()
                        except Exception:
                            posted_at = None
                    loc = item.get('location') or {}
                    city = loc.get('city') or ''
                    country = (loc.get('country') or {}).get('code') if isinstance(loc.get('country'), dict) else (loc.get('country') or '')
                    location = ', '.join([p for p in [city, country] if p]).strip(', ')
                    company = (item.get('company') or {}).get('identifier') or slug
                    jobad = item.get('jobAd') or {}
                    sections = jobad.get('sections') or {}
                    jd = sections.get('jobDescription') or {}
                    desc = jd.get('text') or None
                    jobs.append(Job(title=title, company=company, location=location, posted_at=posted_at, url=link, description=desc, source='smartrecruiters', tags=[]))
            except Exception as e:
                logger.debug(f"[smartrecruiters] {slug} fetch error: {e}")
        logger.info(f"[+] smartrecruiters: {len(jobs)}")
        return jobs

    id: str
    title: str
    company: str
    location: str
    countries_allowed: List[str]
    is_remote: bool
    url: str
    source: str
    posted_at: Optional[str]
    description: Optional[str]
    tags: List[str]
    salary: Optional[str]
    score: Optional[int] = None
    remote_flag: Optional[str] = None

def _parse_date(v: Optional[str]) -> Optional[str]:
    if not v: return None
    try: return dtparse.parse(v).astimezone(timezone.utc).isoformat()
    except Exception: return None

def _canon_country(s: str) -> str:
    key = s.strip().lower()
    return COUNTRY_ALIASES.get(key, s.strip())

def _split_countries(s: Optional[str]) -> List[str]:
    if not s: return []
    parts = re.split(r"[,/;]|\bor\b|\band\b", s, flags=re.I)
    return list(dict.fromkeys([_canon_country(p.strip()) for p in parts if p.strip()]))

def _travel_percent(text: str) -> Optional[int]:
    m = re.search(r"(?i)(?:travel).*?(\d{1,2})\s?%", text)
    if m:
        try: return int(m.group(1))
        except Exception: return None
    return None

def _has_clearance_req(text: str) -> bool:
    return bool(CLEARANCE_RE.search(text or ""))

class BaseProvider:
    name = "base"
    def fetch(self, keywords: List[str]) -> List[Dict[str, Any]]: ...
    def to_jobs(self, raw: List[Dict[str, Any]]) -> List["Job"]: ...

class RemotiveAPI(BaseProvider):
    name = "remotive"
    def fetch(self, keywords: List[str]) -> List[Dict[str, Any]]:
        url = "https://remotive.com/api/remote-jobs"
        with httpx.Client(timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
            r = client.get(url, params={"search": ",".join(keywords) if keywords else "sales engineer"})
            r.raise_for_status()
            return r.json().get("jobs", [])
    def to_jobs(self, raw: List[Dict[str, Any]]) -> List["Job"]:
        out: List[Job] = []
        for j in raw:
            loc = j.get("candidate_required_location") or j.get("job_type") or "Remote"
            out.append(Job(
                id=f"remotive:{j.get('id')}",
                title=j.get("title") or "",
                company=j.get("company_name") or "",
                location=loc,
                countries_allowed=_split_countries(loc) or ["Anywhere"],
                is_remote=True,
                url=j.get("url") or "",
                source=self.name,
                posted_at=_parse_date(j.get("publication_date")),
                description=j.get("description"),
                tags=list(j.get("tags") or []),
                salary=j.get("salary"),
            ))
        return out

class RemoteOKAPI(BaseProvider):
    name = "remoteok"
    def fetch(self, keywords: List[str]) -> List[Dict[str, Any]]:
        with httpx.Client(timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
            r = client.get("https://remoteok.com/api")
            r.raise_for_status()
            data = r.json()
        rows = [d for d in data if isinstance(d, dict) and d.get("id")]
        out = []
        kw = [k.lower() for k in (keywords or DEFAULT_KEYWORDS)]
        for d in rows:
            text = " ".join([
                str(d.get("position", "")),
                str(d.get("company", "")),
                " ".join(d.get("tags") or []),
                str(d.get("description", "")),
            ]).lower()
            if any(k in text for k in kw):
                out.append(d)
        return out
    def to_jobs(self, raw: List[Dict[str, Any]]) -> List["Job"]:
        out: List[Job] = []
        for j in raw:
            loc = j.get("location") or "Remote"
            out.append(Job(
                id=f"remoteok:{j.get('id')}",
                title=j.get("position") or "",
                company=j.get("company") or "",
                location=loc,
                countries_allowed=_split_countries(loc) or ["Anywhere"],
                is_remote=bool(j.get("remote", True)),
                url=j.get("url") or ("https://remoteok.com/" + str(j.get("slug", ""))),
                source=self.name,
                posted_at=_parse_date(j.get("date")),
                description=j.get("description"),
                tags=list(j.get("tags") or []),
                salary=j.get("salary"),
            ))
        return out

class GreenhouseAPI(BaseProvider):
    name = "greenhouse"
    def fetch(self, keywords: List[str]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        with httpx.Client(timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
            for org in GREENHOUSE_COMPANIES:
                url = f"https://boards-api.greenhouse.io/v1/boards/{org}/jobs"
                try:
                    r = client.get(url); r.raise_for_status()
                    data = r.json()
                    for j in data.get("jobs", []):
                        j["_gh_org"] = org
                        out.append(j)
                except Exception:
                    continue
        return out
    def to_jobs(self, raw: List[Dict[str, Any]]) -> List["Job"]:
        jobs: List[Job] = []
        for j in raw:
            title = j.get("title") or ""
            company = j.get("_gh_org", "")
            url = j.get("absolute_url") or ""
            locs = []
            for l in j.get("locations", []) or []:
                name = l.get("name") if isinstance(l, dict) else str(l)
                if name: locs.append(name)
            location = ", ".join(locs) or "Remote"
            desc = j.get("content") or ""
            jobs.append(Job(
                id=f"gh:{j.get('id')}:{company}",
                title=title, company=company, location=location,
                countries_allowed=_split_countries(location) or ["Anywhere"],
                is_remote=("remote" in location.lower() or "anywhere" in location.lower() or "global" in location.lower()),
                url=url, source=self.name,
                posted_at=_parse_date(j.get("updated_at") or j.get("created_at")),
                description=desc, tags=[], salary=None,
            ))
        return jobs

class LeverAPI(BaseProvider):
    name = "lever"
    def fetch(self, keywords: List[str]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        with httpx.Client(timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
            for org in LEVER_COMPANIES:
                url = f"https://api.lever.co/v0/postings/{org}?mode=json"
                try:
                    r = client.get(url); r.raise_for_status()
                    postings = r.json()
                    for p in postings:
                        p["_lever_org"] = org
                        out.append(p)
                except Exception:
                    continue
        return out
    def to_jobs(self, raw: List[Dict[str, Any]]) -> List["Job"]:
        jobs: List[Job] = []
        for p in raw:
            title = p.get("text") or ""
            company = p.get("_lever_org", "")
            url = p.get("hostedUrl") or p.get("applyUrl") or ""
            loc = (p.get("categories", {}) or {}).get("location") or p.get("workType") or "Remote"
            desc = p.get("descriptionPlain") or p.get("description") or ""
            tags = p.get("tags") or []
            posted = None
            if p.get("createdAt"):
                try: posted = datetime.fromtimestamp(p["createdAt"] / 1000, tz=timezone.utc).isoformat()
                except Exception: posted = None
            jobs.append(Job(
                id=f"lever:{p.get('id')}:{company}",
                title=title, company=company, location=loc,
                countries_allowed=_split_countries(loc) or ["Anywhere"],
                is_remote=("remote" in (loc or "").lower() or "anywhere" in (loc or "").lower() or "global" in (loc or "").lower()),
                url=url, source=self.name, posted_at=posted, description=desc, tags=list(tags), salary=None
            ))
        return jobs

PROVIDERS: List[BaseProvider] = [RemotiveAPI(), RemoteOKAPI(), GreenhouseAPI(), LeverAPI()]

# ===================== Filters & Scoring =====================
def dedupe(jobs: List[Job]) -> List[Job]:
    seen: Dict[str, Job] = {}
    for j in jobs:
        key = f"{(j.title or '').lower()}::{(j.company or '').lower()}" or (j.url or "").lower()
        if key not in seen or (not seen[key].posted_at and j.posted_at):
            seen[key] = j
    return list(seen.values())

def filter_geography_and_recency(jobs: List[Job], include: List[str], exclude: List[str], days: Optional[int]) -> List[Job]:
    include_c = {_canon_country(c) for c in include if c}
    exclude_c = {_canon_country(c) for c in exclude if c}
    def ok(j: Job) -> bool:
        allowed = set([_canon_country(c) for c in (j.countries_allowed or [])]) or {"Anywhere"}
        if include_c and not (allowed & include_c) and "Anywhere" not in include_c:
            return False
        if exclude_c and (allowed & exclude_c):
            return False
        if days and j.posted_at:
            try:
                age = (datetime.now(timezone.utc) - dtparse.parse(j.posted_at)).days
                if age > days: return False
            except Exception: pass
        return True
    return [j for j in jobs if ok(j)]

def filter_titles(jobs: List[Job], loose: bool) -> List[Job]:
    kept: List[Job] = []
    for j in jobs:
        t = (j.title or "").strip()

        # Hard drop obvious management/leadership titles
        if TITLE_HARDDROP.search(t):
            continue

        # Optional: drop Architect-heavy titles unless junior/associate
        if NO_ARCHITECT and re.search(r"(?i)\b(architect|solutions? architect)\b", t):
            if not re.search(r"(?i)\b(associate|jr|junior|entry|grad|ii)\b", t):
                continue
        if TITLE_DROP_RE.search(t):
            continue
        if TITLE_KEEP_RE.search(t):
            kept.append(j); continue
        if TITLE_SYSTEMS_RE.search(t):
            hay = " ".join([t, j.description or "", " ".join(j.tags or [])])
            if TITLE_SALESY_NEARBY_RE.search(hay) or loose:
                kept.append(j); continue
        if loose and re.search(r"(?i)\b(technical\s+consultant|integration\s+specialist|deployment\s+engineer|customer\s+success\s+engineer|partner\s+engineer)\b", t):
            kept.append(j)
    return kept

def filter_body_signals(jobs: List[Job], strict: bool) -> List[Job]:
    out: List[Job] = []
    for j in jobs:
        hay = " ".join([j.title or "", j.company or "", " ".join(j.tags or []), j.description or ""]).lower()
        if any(bad in hay for bad in EXCLUDE_SIGNALS) or _has_clearance_req(hay):
            continue
        if strict:
            if any(sig in hay for sig in INCLUDE_SIGNALS):
                out.append(j)
        else:
            out.append(j)
    return out

def filter_seniority(jobs: List[Job]) -> List[Job]:
    out = []
    for j in jobs:
        t = (j.title or "")
        # Hard-drop management phrases even if other filters pass
        if re.search(r"(?i)(head of|regional manager|manager of)", t):
            continue
        if SENIORITY_EXCLUDE.search(t) and not SENIORITY_INCLUDE_HINTS.search(t):
            continue
        out.append(j)
    return out

def compute_score(j: Job) -> int:
    text = " ".join([j.title or "", j.location or "", j.description or "", " ".join(j.tags or [])]).lower()
    # Title points
    if TITLE_KEEP_RE.search(j.title or ""): title_points = 30
    elif TITLE_SYSTEMS_RE.search(j.title or "") and TITLE_SALESY_NEARBY_RE.search(text): title_points = 22
    elif re.search(r"(?i)\b(customer\s+success\s+engineer|partner\s+engineer|technical\s+consultant|integration\s+specialist|deployment\s+engineer|value\s+engineer)\b", j.title or ""):
        title_points = 18
    else:
        title_points = 0

    # Responsibilities
    resp_terms = ["discovery","demo","poc","proof of concept","rfi","rfp","solution design","architecture","pilot","enablement","scoping","sow"]
    responsibilities_points = min(25, sum(5 for t in resp_terms if t in text))

    # Tech
    tech_core = 8 if any(t in text for t in ["api","integration","webhook","rest","graphql"]) else 0
    tech_lang = sum(1 for t in ["linux","python","sql"] if t in text)
    tech_auth_cloud = sum(1 for t in ["oauth","saml","sso","aws","azure","gcp","docker","kubernetes","postman","curl","sdk","cli"] if t in text)
    tech_points = min(20, tech_core + min(7, tech_lang) + min(5, tech_auth_cloud))

    # Remote/eligibility
    remote_points = 0
    if any(t in text for t in ["remote","work from anywhere","distributed","hybrid","work from home"]): remote_points += 10
    if any(t in text for t in ["remote (us)","remote (australia)","remote usa","remote us","remote au","anywhere in the us","anywhere in australia","global remote","united states","australia"]): remote_points += 5
    remote_points = min(15, remote_points)

    # Compensation (best-effort)
    comp_points = 1
    m = re.search(r"(?i)(?:\$|usd)\s?(\d{2,3})(?:[,\.]?\d{3})?", text)
    if m:
        num = int(m.group(1))
        if num >= 90: comp_points = 5
        elif num >= 70: comp_points = 3

    # Travel
    travel = _travel_percent(text)
    travel_points = 5 if (travel is None or travel <= 25) else (3 if travel <= 30 else 0)

    # Bonuses / penalties
    bonus = 0
    if re.search(r"(?i)\bred\s*dot\b|award", text): bonus += 3
    if "automation" in text or "scripting" in text or "pipeline" in text: bonus += 3
    if "documentation" in text or "rfp" in text: bonus += 3

    penalty = 0
    if "on-site only" in text or "onsite only" in text or "no remote" in text: penalty -= 25
    if _has_clearance_req(text): penalty -= 30
    if any(t in text for t in ["ticket queue","pager duty","incident response","rack and stack","install cable","break/fix"]):
        penalty -= 18
    if travel is not None and travel > 30: penalty -= 10
    if SENIORITY_EXCLUDE.search(j.title or "") and not SENIORITY_INCLUDE_HINTS.search(j.title or ""): penalty -= 8

    total = max(0, min(100, title_points + responsibilities_points + tech_points + remote_points + comp_points + travel_points + bonus + penalty))
    return total

def annotate_remote_flag(j: Job) -> str:
    loc = (j.location or "").lower()
    if "remote" in loc or j.is_remote: return "Remote"
    if "hybrid" in loc: return "Hybrid"
    return "Onsite/Unknown"

# ===================== Orchestration =====================
def collect_jobs(keywords: List[str]) -> List[Job]:
    all_jobs: List[Job] = []
    for p in PROVIDERS:
        try:
            raw = p.fetch(keywords); jobs = p.to_jobs(raw); all_jobs.extend(jobs)
            log.info(f"[+] {p.name}: {len(jobs)}")
        except Exception as e:
            log.warning(f"[WARN] {p.name} failed: {e}")
    return all_jobs

def apply_filters_and_score(jobs: List[Job], min_keep_score: int, loose: bool, strict: bool, console: Console) -> List[Job]:
    console.print(f"[dim]Filter: loose={loose} strict={strict} min={min_keep_score}[/dim]")
    jobs = filter_titles(jobs, loose=loose)
    jobs = filter_body_signals(jobs, strict=strict)
    jobs = filter_seniority(jobs)

    out: List[Job] = []
    for j in jobs:
        text = " ".join([j.title or "", j.description or ""])
        if _has_clearance_req(text):
            continue
        j.score = compute_score(j)
        j.remote_flag = annotate_remote_flag(j)
        if j.score is not None and j.score >= min_keep_score:
            out.append(j)

    if not out and not strict:
        console.print("[yellow]No jobs met min score; widening by taking top title matches.[/yellow]")
        temp = []
        for j in jobs:
            base = 0
            if TITLE_KEEP_RE.search(j.title or ""): base = 30
            elif TITLE_SYSTEMS_RE.search(j.title or ""): base = 22
            elif re.search(r"(?i)\b(customer\s+success\s+engineer|partner\s+engineer|technical\s+consultant|integration\s+specialist|deployment\s+engineer|value\s+engineer)\b", j.title or ""):
                base = 18
            temp.append((base, j))
        temp.sort(key=lambda x: (x[0], x[1].posted_at or ""), reverse=True)
        out = [j for base, j in temp[:100]]
    return out

# ===================== Output =====================
def as_table(jobs: List[Job]) -> Table:
    t = Table(show_header=True, header_style="bold")
    t.add_column("Title", min_width=28)
    t.add_column("Company", min_width=18)
    t.add_column("Location", min_width=16)
    t.add_column("When", min_width=10)
    t.add_column("Score", min_width=8, justify="right")
    t.add_column("Remote", min_width=8)
    t.add_column("Source", min_width=12)
    t.add_column("URL", min_width=22)
    for j in jobs:
        when = j.posted_at[:10] if j.posted_at else "—"
        t.add_row(j.title, j.company, j.location, when, str(j.score or "—"), j.remote_flag or "—", j.source, j.url)
    return t

def ensure_dir(path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)

def save_csv(jobs: List[Job], path: str) -> None:
    ensure_dir(path)
    fields = list(asdict(jobs[0]).keys()) if jobs else list(Job.__annotations__.keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for j in jobs:
            w.writerow(asdict(j))

def save_json(jobs: List[Job], path: str) -> None:
    ensure_dir(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([asdict(j) for j in jobs], f, ensure_ascii=False, indent=2)

# ===================== Mail =====================
def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    return default if v is None else v.strip().lower() in {"1","true","yes","y","on"}

def chunked(seq: List[Job], size: int) -> List[List[Job]]:
    return [seq[i:i+size] for i in range(0, len(seq), size)]

def send_email_with_attachment(subject: str, body: str, attachment_path: str) -> None:
    smtp_host = os.getenv("SMTP_HOST","smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT","587"))
    smtp_ssl  = _env_bool("SMTP_SSL", False)
    smtp_user = os.getenv("SMTP_USER") or os.getenv("SMTP_USERNAME")
    smtp_pass = os.getenv("SMTP_PASS") or os.getenv("SMTP_PASSWORD")
    to_email  = os.getenv("EMAIL_TO") or os.getenv("TO_EMAIL") or os.getenv("DIGEST_TO")
    from_email= os.getenv("EMAIL_FROM") or smtp_user
    reply_to  = os.getenv("REPLY_TO") or from_email
    if not (smtp_host and smtp_user and smtp_pass and to_email):
        raise RuntimeError("SMTP config missing")
    msg = MIMEMultipart()
    msg["From"], msg["To"], msg["Subject"] = from_email, to_email, subject
    msg.add_header("Reply-To", reply_to)
    msg.attach(MIMEText(body, "plain", _charset="utf-8"))
    if attachment_path and os.path.exists(attachment_path):
        with open(attachment_path, "rb") as f:
            part = MIMEBase("application","octet-stream")
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f"attachment; filename=%s" % os.path.basename(attachment_path))
            msg.attach(part)
    if smtp_ssl:
        server = smtplib.SMTP_SSL(smtp_host, smtp_port)
    else:
        server = smtplib.SMTP(smtp_host, smtp_port); server.ehlo()
        try: server.starttls()
        except Exception: pass
    server.login(smtp_user, smtp_pass); server.send_message(msg); server.quit()
    log.info(f"[OK] Sent email → {to_email} ({os.path.basename(attachment_path)})")

def build_cover_message(provider_summary: str = "", flags_summary: str = "") -> str:
    return f"""Hello,

Attached is today’s batch of {ROLE_FAMILY} opportunities.

Signals we care about:
- Presales motions: discovery/demo/POC/RFI-RFP
- Tech: APIs/integrations, auth (OAuth/SAML/SSO), Linux/Python/SQL, cloud
- Remote friendly, US or AU eligible preferred

Work rights: US green card + SSN; Australian citizen.

{("Providers: " + provider_summary) if provider_summary else ""}
{("Run flags: " + flags_summary) if flags_summary else ""}
"""

# ===================== CLI / Main =====================
def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=f"ApplyPilot Ultra — {ROLE_FAMILY}")
    ap.add_argument("-k","--keywords", default=",".join(DEFAULT_KEYWORDS), help="Comma-separated keywords")
    ap.add_argument("--include-countries", default=DEFAULT_INCLUDE, help="Comma-separated countries/regions to include")
    ap.add_argument("--exclude-countries", default="", help="Comma-separated countries/regions to exclude")
    ap.add_argument("--days", type=int, default=int(os.getenv("MAX_AGE_DAYS","30")), help="Only include jobs posted within N days (0 = all)")
    ap.add_argument("--max", type=int, default=4000, help="Max rows to keep")
    ap.add_argument("--print", action="store_true", help="Print a table")
    ap.add_argument("-o","--csv", default=os.getenv("JOBS_CSV_PATH","./data/se_filtered_jobs.csv"), help="CSV path")
    ap.add_argument("--json", default=os.getenv("RAW_JOBS_CSV","./data/se_jobs_all.json"), help="JSON path")
    ap.add_argument("--email", action="store_true", help="Send email batches")
    ap.add_argument("--loose", action="store_true", help="Loosen filters (skip body-signal gate; widen title keepers)")
    ap.add_argument("--strict", action="store_true", help="Strict body-signal requirement")
    ap.add_argument("--min-score", type=int, default=int(os.getenv("MIN_KEEP_SCORE","50")), help="Minimum score to keep (default 50)")
    return ap.parse_args()

def build_subject(score_avg: int, count: int, batch_idx: int, batch_total: int) -> str:
    return f"{EMAIL_SUBJECT_PREFIX} {EMAIL_BASE_SUBJECT} — Batch {batch_idx}/{batch_total} ({count} roles, avg={score_avg})"

def main() -> int:
    console = Console()
    args = parse_args()

    keywords  = [s.strip() for s in (args.keywords or "").split(",") if s.strip()]
    include_c = [s.strip() for s in (args.include_countries or "").split(",") if s.strip()]
    exclude_c = [s.strip() for s in (args.exclude_countries or "").split(",") if s.strip()]

    console.print(f"[dim]Collecting with providers={len(PROVIDERS)}[/dim]")
    jobs = collect_jobs(keywords)
    console.print(f"Collected: {len(jobs)}")

    jobs = dedupe(jobs); console.print(f"After dedupe: {len(jobs)}")
    jobs = filter_geography_and_recency(jobs, include_c, exclude_c, None if args.days == 0 else args.days)
    console.print(f"After geo/date: {len(jobs)}")

    jobs = apply_filters_and_score(jobs, min_keep_score=args.min_score, loose=args.loose, strict=args.strict, console=console)
    console.print(f"After SE filters+score: {len(jobs)}")

    # Sort by score then recency
    jobs.sort(key=lambda j: ((j.score or 0), j.posted_at or ""), reverse=True)

    if args.max and len(jobs) > args.max:
        jobs = jobs[:args.max]
    console.print(f"[dim]Final: {len(jobs)}[/dim]")

    if args.csv:
        save_csv(jobs, args.csv); print(f"[OK] CSV written to {args.csv}")
    if args.json:
        save_json(jobs, args.json); print(f"[OK] JSON written to {args.json}")

    if args.print or not (args.csv or args.json):
        if jobs:
            console.print(as_table(jobs)); console.print(f"\n[dim]{len(jobs)} jobs shown.[/dim]")
        else:
            console.print("[yellow]No jobs to show. Try --loose or lower --min-score.[/yellow]")

    enable_email = args.email or _env_bool("ENABLE_EMAIL", False)
    if enable_email and jobs:
        Path("./data").mkdir(exist_ok=True)
        batch_size = int(os.getenv("EMAIL_BATCH_SIZE","100"))
        delay_s    = int(os.getenv("EMAIL_BATCH_DELAY_SECONDS","2"))

        # Summaries for the email body
        provider_counts: Dict[str,int] = {}
        for _j in jobs:
            provider_counts[_j.source] = provider_counts.get(_j.source, 0) + 1
        provider_summary = ", ".join(f"{k}:{v}" for k, v in sorted(provider_counts.items(), key=lambda kv: (-kv[1], kv[0])))

        flags_summary = " ".join(arg for arg in [
            "--loose" if args.loose else "",
            "--strict" if args.strict else "",
            f"--min-score {args.min_score}",
            f"--days {args.days}",
            f"--max {args.max}",
        ] if arg)

        body = build_cover_message(provider_summary, flags_summary)

        batches = chunked(jobs, batch_size)
        for idx, chunk in enumerate(batches, start=1):
            batch_path = Path("./data") / f"se_jobs_batch_{idx}.csv"
            save_csv(chunk, str(batch_path))
            scores = [c.score or 0 for c in chunk]
            score_avg = (sum(scores)//len(scores)) if scores else 0
            subject = build_subject(score_avg, len(chunk), idx, len(batches))
            send_email_with_attachment(subject, body, str(batch_path))
            if delay_s and idx < len(batches): time.sleep(delay_s)
    elif enable_email and not jobs:
        print("[WARN] Email enabled but there are 0 jobs. Skipping email.")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
NO_ARCHITECT = False  # set from --no-architect

def fetch_smartrecruiters(companies_file: Path | str = None) -> List[Job]:
    """
    Collect postings from SmartRecruiters per-company JSON endpoint.
    Company slugs are read from a newline-delimited file.
    """
    file_path = Path(companies_file or os.getenv("SMARTRECRUITERS_FILE", "./data/smartrecruiters_companies.txt"))
    jobs: List[Job] = []

#         return jobs  # patched: stray top-level return

    try:
        lines = [ln.strip() for ln in file_path.read_text(encoding="utf-8").splitlines()]
        slugs = [ln for ln in lines if ln and not ln.startswith("#")]
    except Exception as e:
        logger.warning(f"[smartrecruiters] could not read {file_path}: {e}")
        slugs = []

    if not slugs:
        logger.info("[+] smartrecruiters: 0 (no company slugs)")
#         return jobs  # patched: stray top-level return

    headers = {"User-Agent": USER_AGENT}
    client = httpx.Client(headers=headers, timeout=REQUEST_TIMEOUT)
    for slug in slugs:
        url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100"
        try:
            r = client.get(url)
            if r.status_code != 200:
                logger.debug(f"[smartrecruiters] {slug} -> {r.status_code}")
                continue
            data = r.json()
            for item in data.get("content", []):
                title = (item.get("name") or "").strip()
                ref = item.get("ref", {}) or {}
                link = ref.get("jobAdUrl") or ref.get("uri") or f"https://www.smartrecruiters.com/{slug}/{item.get('id','')}"
                dstr = item.get("releasedDate") or item.get("createdOn")
                posted_at = None
                if dstr:
                    try:
                        posted_at = dtparse.parse(dstr).date()
                    except Exception:
                        posted_at = None
                loc = item.get("location") or {}
                city = loc.get("city") or ""
                country = (loc.get("country") or {}).get("code") if isinstance(loc.get("country"), dict) else (loc.get("country") or "")
                location = ", ".join([p for p in [city, country] if p]).strip(", ")
                company = (item.get("company") or {}).get("identifier") or slug
                desc = None
                jobad = item.get("jobAd") or {}
                sections = jobad.get("sections") or {}
                jd = sections.get("jobDescription") or {}
                desc = jd.get("text") or None

                jobs.append(Job(
                    title=title, company=company, location=location,
                    posted_at=posted_at, url=link, description=desc,
                    source="smartrecruiters", tags=[]
                ))
        except Exception as e:
            logger.debug(f"[smartrecruiters] {slug} fetch error: {e}")

    logger.info(f"[+] smartrecruiters: {len(jobs)}")
#     return jobs  # patched: stray top-level return

def fetch_smartrecruiters_jobs(lines):
    return Job.fetch_smartrecruiters_jobs(lines)
