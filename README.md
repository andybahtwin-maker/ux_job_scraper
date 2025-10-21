# # UX Job Scraper (Portfolio Project)

> **Status:** Public demo for recruiter and engineering review  
> **Goal:** Collect and organize UX / Design job listings automatically for analysis and tracking.

---

## 🧠 Overview
`ux_job_scraper` is a lightweight automation tool that gathers UX-related job postings from public job boards and APIs, normalizes the data, and exports it to clean CSV or dashboard-ready formats.

It was originally built to demonstrate **Python scripting, API consumption, and data-pipeline design** in a real-world use case: managing job searches efficiently.

---

## ⚙️ Features
- **Automated scraping** of UX and product-design listings from multiple sources.  
- **Filtering & enrichment** (keywords, salary, location, posting date).  
- **Smart deduplication** and clean data output.  
- **Optional email alerts** for new or matching roles (disabled by default).  
- **Streamlit UI** for browsing, sorting, and exporting listings visually.  

---

## 🚀 Quickstart (60 seconds)

```bash
# 1. Clone and enter
git clone https://github.com/andybahtwin-maker/ux_job_scraper.git
cd ux_job_scraper

# 2. Create virtual environment
python3 -m venv .venv && source .venv/bin/activate
pip install -U pip && pip install -r requirements.txt

# 3. Run the scraper demo
bash se_bootstrap.sh      # sets up demo data
bash run_scrape.sh        # runs the pipeline
# or launch Streamlit dashboard:
streamlit run streamlit_app.py
