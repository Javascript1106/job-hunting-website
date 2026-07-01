# PathForge

PathForge is a hybrid job-hunting platform designed to help users not only find jobs, but successfully obtain them through AI-assisted career tools.

The long-term goal is to combine traditional job searching with modern AI-powered assistance while keeping the platform accessible, educational, and user-friendly for job seekers of all experience levels.

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

## Chatbot Enhancements ✅

* Modern chat bubbles
* Conversation history
* Auto-scroll
* Enter-to-send
* Typing indicator
* Message animations
* Quick suggestion buttons
* Floating chatbot launcher
* Responsive chatbot styling

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
├── database.py
├── jobs.db

├── README.md
├── future-features.md

---

# Running PathForge Locally

## Start the Backend

Open a terminal inside the project folder and run:

python -m uvicorn main:app --reload

FastAPI should start on:

http://127.0.0.1:8000

## Start the Frontend

Use:

* VS Code Live Server (recommended)

or

* Open the HTML files directly in a web browser.

Recommended starting page:

index.html

---

# Current API Endpoints

GET /

Returns backend status.

GET /jobs

Returns all jobs.

POST /jobs

Creates a new job.

POST /chat

Sends a message to the AI assistant.

DELETE /jobs/{id}

Deletes a job.

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

* Week 4 - Authentication System
* Week 5 - User Dashboard
* Week 6 - Employer Features
* Week 7 - Advanced Search
* Week 8 - AI Assistant Expansion
* Week 9 - Polish, Home Page Redesign, Branding & Testing
* Week 10+ - Launch Preparation, Monetization & Deployment
