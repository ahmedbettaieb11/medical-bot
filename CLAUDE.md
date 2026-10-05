# Medical Alert Bot — Tunisia

## What this project is
A Python bot that monitors Tunisian health sources around the clock and alerts pharmaceutical companies about outbreaks and epidemics. For each event it estimates which product categories will rise or drop in demand, with magnitude and a confidence level.

Status: personal/portfolio project for now. Possibly sold to multiple Tunisian pharma companies later.

## IMPORTANT: how to work with Oussama
- Oussama is NEW to Python. He does not write the code; Claude writes it and he runs it.
- For every step, give: exact commands to type (one at a time), what each command does in plain language, and what he should see if it worked.
- Never assume he knows Python concepts (virtual environments, pip, imports, .env files, git). Explain each one briefly the first time it appears.
- Keep steps small. After each step, have him run something and confirm it works before moving on.
- When he pastes an error, explain what went wrong in simple terms, then fix it.
- He is comfortable with web tools, WordPress, and automation workflows, so analogies to those help.

## Decisions already made
- **Geographic scope:** Tunisia only.
- **Alert content:** full demand estimates with numbers and confidence levels. Note: real unit numbers need historical sales data (not public in Tunisia). Until a data partner exists, produce relative estimates (direction + magnitude + confidence) from case counts, seasonality, past outbreak patterns, and proxies like Google Trends. Be transparent about how each estimate is derived.
- **Delivery:** Telegram message for urgent alerts + a web dashboard for everything. (WhatsApp later, if sold.)
- **Language:** Python.
- **Budget:** free while it's a personal project.

## Sources to monitor
- Tunisian Ministry of Health
- ONMNE (Observatoire National des Maladies Nouvelles et Émergentes) — usually the earliest official signal
- INSP (Institut National de Santé Publique)
- WHO Tunisia country office and WHO EMRO bulletins
- WHO Disease Outbreak News (filtered to Tunisia)
- TAP news agency + major Tunisian news sites (Arabic and French)
- Facebook pages: much official communication happens there, but scraping is hard and against ToS. Defer.

Verify each site's actual structure (RSS feed available? HTML layout?) before writing its scraper. Respect robots.txt and add polite delays.

Source status (checked 2026-10-05 from Tunisia):
- ONMNE: WordPress; RSS broken, read via REST API (`/?rest_route=/wp/v2/posts`). Site has injected spam posts (category 427), which are skipped. Posts rarely (last health post Sept 2025).
- Ministry of Health: santetunisie.rns.tn doesn't resolve; sante.gov.tn shows a default XAMPP page. No usable site; it communicates mainly via Facebook (deferred).
- INSP (insp.rns.tn): "site en cours de construction". Nothing to read.
- TAP: certificate chain misconfigured + intermittent "no route to host". Skipped; La Presse/Babnet republish TAP dispatches.
- WHO EMRO Tunisia: RSS feed exists but is empty. WHO DON API covers outbreaks.

## Pipeline
1. **Collect:** scrapers/RSS readers pull new articles every 30–60 min; fingerprint to deduplicate the same story across outlets.
2. **Understand:** AI model reads Arabic/French articles → is it health-relevant? Extract disease, governorate, case counts, severity, trend.
3. **Estimate:** disease→product category mapping + seasonal baselines + past outbreak patterns → direction, magnitude, confidence.
4. **Alert:** high severity → instant Telegram message; everything → dashboard.

## Free stack
- Scheduling: GitHub Actions (cron)
- Scraping: requests, BeautifulSoup, feedparser, trafilatura
- AI analysis: Google Gemini free tier (or a local model)
- Storage: SQLite to start (Supabase free tier if the dashboard needs live reads)
- Dashboard: Streamlit on Streamlit Community Cloud
- Alerts: Telegram Bot API

## Paid stack (if it becomes a product, ~$30–60/month)
Small VPS (e.g. Hetzner), PostgreSQL, paid AI API, WhatsApp Business API, uptime monitoring. The real investment is a sales-data partnership (distributor or Pharmacie Centrale) and a pharmacist/medical advisor to validate the disease→product mappings, plus clear disclaimers.

## Build phases
- **Phase 1:** project setup, scrapers, database, Telegram alert for every new health article.  ← START HERE
- **Phase 2:** AI extraction + event deduplication.
- **Phase 3:** demand estimation + confidence scoring.
- **Phase 4:** Streamlit dashboard.

Each phase should end with something working and demo-able.
