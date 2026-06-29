from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import sqlite3

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_NAME = "jobs.db"

class ChatMessage(BaseModel):
    message: str

class Job(BaseModel):
    title: str
    company: str
    location: str
    pay: str
    description: str
    schedule: str
    experience: str
    category: str

@app.get("/")
def home():
    return {"message": "Job hunting website backend is running"}

@app.get("/jobs")
def get_jobs():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM jobs")
    rows = cursor.fetchall()

    jobs = []
    for row in rows:
        jobs.append(dict(row))

    conn.close()
    return jobs

@app.post("/jobs")
def add_job(job: Job):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO jobs (
            title,
            company,
            location,
            pay,
            description,
            schedule,
            experience,
            category
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        job.title,
        job.company,
        job.location,
        job.pay,
        job.description,
        job.schedule,
        job.experience,
        job.category
    ))

    conn.commit()
    conn.close()

    return {"message": "Job added successfully"}

@app.delete("/jobs/{job_id}")
def delete_job(job_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

    conn.commit()
    conn.close()

    return {"message": f"Job {job_id} deleted successfully"}

@app.post("/chat")
def chat(data: ChatMessage):
    message = data.message.lower()

    if "resume" in message:
        reply = "I can help improve your resume by matching your skills to the job."
    elif "interview" in message:
        reply = "I can help you practice interview answers and prepare strong responses."
    elif "job" in message:
        reply = "I can help you find jobs based on location, schedule, experience, and age requirements."
    else:
        reply = "I can help with job searching, resumes, applications, interviews, and career planning."

    return {"reply": reply}