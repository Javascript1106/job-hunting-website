# README.md

# PathForge

PathForge is a hybrid job-hunting platform designed to help users not only find jobs, but successfully obtain them through AI-assisted career tools.

The long-term goal is to combine traditional job searching with modern AI-powered assistance while keeping the platform accessible, educational, and user-friendly for job seekers of all experience levels.

---

# Target Completion Date

Current target completion date:

**August 16, 2026**

This accelerated timeline allows the project to be completed before Fall 2026 college coursework begins.

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

## Interview Learning Center Assistant (Planned Week 8)

Separate from the main assistant.

Purpose:

* Mock interviews
* Interview coaching
* Interview evaluations
* Interview practice
* Authenticity scoring
* Personalized feedback

Both assistants share backend infrastructure while providing specialized experiences.

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

Planned:

* Password hashing
* Authentication
* Session management
* Protected routes
* Secure logout
* Duplicate account prevention

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

* Open HTML files directly in a browser.

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
