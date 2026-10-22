# README.md

# PathForge

PathForge is a job-search and hiring platform that combines a verified opportunity catalog, application organization, employer workflows, practical career resources, and clearly bounded AI assistance.

The long-term goal is to combine traditional job searching with modern AI-powered assistance while keeping the platform accessible, educational, and user-friendly for job seekers of all experience levels.

---

# Current Status

PathForge is under active development. Core job-seeker, employer, catalog,
resource, messaging, analytics, authentication, and moderation workflows are
implemented. Run the automated suite before merging changes.

---

# Current Features

## Week 1 - Jobs Experience Foundation ✅

* Multi-page website structure
* Shared navigation
* Shared styling
* Responsive layout
* FastAPI backend setup
* Frontend ↔ backend communication
* Jobs page layout
* Search UI
* Job cards
* Chatbot integration

## Week 2 - Dynamic Job System ✅

* Dynamic job loading
* Real-time search filtering
* Location filtering
* Category filtering
* Auto-generated category dropdown
* Expandable job details
* Richer job data model

## Week 3 - SQLite Database Integration ✅

* SQLite database integration
* Job storage in database
* FastAPI database integration
* API endpoints for jobs
* API endpoints for chatbot

## Main Career Assistant Enhancements ✅

Available on:

* Home page
* Jobs page

Features:

* Modern chat bubbles
* Conversation history
* Auto-scroll
* Enter-to-send
* Typing indicator
* Message animations
* Quick suggestion buttons
* Floating chatbot launcher
* Collapsible chatbot window
* Responsive styling

---

# AI Assistant System

PathForge uses multiple specialized AI experiences.

## Main Career Assistant

Purpose:

* General job-search assistance
* Career guidance
* Resume guidance
* Job comparisons
* First-job support
* Career exploration

Available on:

* Home page
* Jobs page

## Resource Center AI Assistant

Available inside the public Resource Center.

Purpose:

* Mock interviews
* Interview coaching
* Interview evaluations
* Interview practice
* Personalized feedback

The Resource Center is a reference library rather than a course. It does not
save lesson completion or learning progress. Mock-interview answers and résumé
document contents are not silently added to connected account history.

---

# Technology Stack

## Frontend

* HTML
* CSS
* JavaScript

## Backend

* Python
* FastAPI

## Database

* SQLite

---

# Security

Implemented:

* Argon2id password hashing with automatic legacy-hash upgrades
* Authentication rate limiting and verification-attempt protection
* Server-side, hashed session tokens
* Protected routes with job-seeker, employer, and administrator checks
* Secure logout and account session revocation
* Duplicate account prevention
* Environment-aware browser security headers and API documentation

---

# Project Structure

job-hunting-website/

├── index.html
├── jobs.html
├── login.html
├── register.html
├── employer.html

├── style.css
├── script.js

├── main.py
├── app_config.py
├── auth.py
├── auth_routes.py
├── job_routes.py
├── saved_job_routes.py
├── schemas.py
├── database.py
├── jobs.db

├── README.md
├── future-features.md

---

# Running PathForge Locally

## Install Python Dependencies

From the project folder, create and activate a virtual environment before
installing the pinned development dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

Use `requirements.txt` instead when a deployed environment needs only runtime
packages. Keeping dependencies pinned makes development, testing, and deployment
use the same verified versions.

## Start the Backend

Apply any pending versioned database migrations before starting a deployed
instance. The command is safe to repeat and reports when the schema is current:

```powershell
python migrate_database.py
```

Development startup also checks for pending migrations, so an existing local
database upgrades automatically without rebuilding or deleting user data.

By default, PathForge stores SQLite data in `jobs.db` inside the project folder,
regardless of which terminal folder starts the backend. To keep the database in
a different location, set an absolute `PATHFORGE_DATABASE_PATH` before running
the migration and backend commands:

```powershell
$env:PATHFORGE_DATABASE_PATH="C:\secure-data\pathforge.db"
python migrate_database.py
```

All application and maintenance-tool connections share the same foreign-key
enforcement and lock-timeout settings.

## Maintain the Job Catalog

Refresh official sources and expire jobs that disappeared from a source that
completed successfully:

```powershell
python sync_jobs.py --mark-stale
```

The command prints live source-by-source progress, followed by JSON containing
the active, closed, stale, empty-source, failed-source, and large-drop health
summary. Use `--quiet` when another program needs JSON-only standard output.

For the scheduler-safe workflow, run `python catalog_maintenance.py`. It creates
a database backup, refreshes every configured source, produces JSON and Markdown
coverage reports in `automation-logs`, and read-only checks up to 50 stale
official links. The latest coverage reports are:

- `automation-logs/catalog-insights-latest.json`
- `automation-logs/catalog-insights-latest.md`

They summarize state coverage, confirmed and possible teen-job coverage,
employer and category balance, and missing listing details. A closed-link result
marks the run as needing attention; scheduled maintenance does not close that
listing automatically.

Run `python site_maintenance.py` for the lightweight daily check. It verifies or
creates a recent database backup, checks SQLite integrity and foreign keys,
removes expired sessions and auth-attempt records older than 30 days, summarizes
recent failed-login activity without storing raw IP addresses, and safely checks
up to 25 stale public job links without changing job status. Its private local
readiness reports are `automation-logs/site-readiness-latest.json` and
`automation-logs/site-readiness-latest.md`.

To register this check in Windows Task Scheduler for 9:15 AM daily (no open
PowerShell window is required), run:

```powershell
$pythonExecutable = (Resolve-Path .\.venv\Scripts\python.exe).Path
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup_local_site_maintenance_task.ps1 -PythonExecutable $pythonExecutable
```

Stale links from manually imported employer pages can be checked separately.
The default command is read-only; add `--apply` to create a verified backup,
close only definitive dead pages, and refresh jobs whose title is confirmed:

```powershell
python verify_job_links.py --stale-days 7 --limit 50
python verify_job_links.py --stale-days 7 --apply
```

Open a terminal inside the project folder and run:

python -m uvicorn main:app --reload

FastAPI should start on:

http://127.0.0.1:8000

Open PathForge in a browser at:

http://127.0.0.1:8000/app

The backend serves an explicit allowlist of frontend pages and public assets.
It does not expose `.env`, `jobs.db`, backups, or source configuration files.

For production, set `PATHFORGE_ENV=production`. If the frontend and API use
different origins, set `PATHFORGE_ALLOWED_ORIGINS` to the exact comma-separated
HTTPS frontend origins before starting the server.

Use `.env.example` as the variable-name template and follow
`DEPLOYMENT.md` before exposing PathForge publicly.

## Optional Separate Frontend

For frontend-only development, you can instead use:

* VS Code Live Server (recommended)

Any localhost port works in development. Do not open the HTML files directly
with a `file://` URL: browsers do not provide a safe credentialed origin for
account and API requests in that mode.

When using a separate frontend server, the recommended starting page is:

index.html

---

# Current API Endpoints

GET /

Returns backend status.

GET /jobs

Returns the complete eligible public-job collection for compatibility.

GET /jobs/catalog?limit=250&offset=0

Returns lightweight, paginated job cards for the live catalog.

GET /jobs/{id}

Returns complete details for one eligible public job.

POST /jobs

Creates a new job.

DELETE /jobs/{id}

Deletes a job.

POST /chat

Sends a message to the AI assistant.

---

# Development Philosophy

* Avoid feature creep.
* Follow the roadmap strictly.
* Finish the current phase before beginning the next.
* Working systems are more important than additional features.
* Preserve previously completed functionality.
* Keep the free experience highly valuable.
* Accessibility features should always remain free.

---

# Accessibility Principles

Accessibility features will always remain free.

Planned features include:

* High contrast mode
* Adjustable text size
* Dyslexia-friendly fonts
* Reduced motion mode
* Screen reader support
* Keyboard navigation
* Colorblind-friendly themes
* Simplified interface mode

---

# Beginner Experience

PathForge is designed to remain approachable for:

* Teenagers
* College students
* Internship seekers
* First-time job seekers
* Career changers
* Experienced professionals

Planned Beginner Mode features:

* Job terminology explanations
* Additional tooltips
* First-job guidance
* Simplified interface options

---

# Target Audience

PathForge is designed for:

* Teenagers seeking first jobs
* College students
* Internship seekers
* Career changers
* Experienced professionals
* Users with accessibility needs

---

# Long-Term Vision

PathForge aims to become a complete career success platform by combining:

* Job search
* Resume assistance
* Interview preparation
* Career guidance
* Application tracking
* Personalized recommendations
* AI-assisted career development

---

# Roadmap

## Week 4 - Authentication System

* User registration
* User login
* Secure logout
* Password hashing
* Session management
* Protected routes

## Week 5 - User Dashboard

* User profiles
* Saved jobs
* Application tracking
* Dashboard widgets
* Personalization
* Calendar reminders

## Week 6 - Employer Features

* Employer accounts
* Employer dashboard
* Create job postings
* Edit job postings
* Delete job postings

## Week 7 - Advanced Search & Accessibility

* Browser geolocation
* Radius search
* Transportation recommendations
* Accessibility improvements
* Beginner mode

## Week 8 - AI Assistant Expansion

* Resume review
* Resume uploads
* Interview Learning Center
* Mock interviews
* Career guidance
* Personalized recommendations
* Job matching

## Week 9 - Polish, Branding & Testing

* Home page redesign
* Branding
* Mobile optimization
* Accessibility testing
* Bug fixes
* Performance optimization

## Week 10+ - Launch Preparation

* Deployment
* Documentation
* Portfolio preparation
* Monetization
* Subscription management
