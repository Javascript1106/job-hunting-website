from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
import hashlib
import os
import sqlite3


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_NAME = "jobs.db"

def hash_password(password: str):
    salt = os.urandom(16).hex()
    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100000
    ).hex()

    return f"{salt}:{password_hash}"


def verify_password(plain_password: str, stored_password: str):
    salt, saved_hash = stored_password.split(":")

    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        plain_password.encode("utf-8"),
        salt.encode("utf-8"),
        100000
    ).hex()

    return password_hash == saved_hash


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


class RegisterUser(BaseModel):
    username: str
    email: EmailStr
    password: str


class LoginUser(BaseModel):
    identifier: str
    password: str


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


@app.post("/register")
def register_user(user: RegisterUser):
    password_bytes = len(user.password.encode("utf-8"))

    if len(user.password) < 8 or password_bytes > 72:
        raise HTTPException(
            status_code=400,
            detail="Password must be between 8 and 72 bytes long."
        )

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM users WHERE email = ? OR username = ?",
        (user.email, user.username)
    )
    existing_user = cursor.fetchone()

    if existing_user:
        conn.close()
        raise HTTPException(
            status_code=400,
            detail="Username or email already exists."
        )

    hashed_password = hash_password(user.password)

    cursor.execute(
        "INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
        (user.username, user.email, hashed_password)
    )

    conn.commit()
    conn.close()

    return {"message": "Account created successfully."}


@app.post("/login")
def login_user(user: LoginUser, response: Response):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
    """
    SELECT id, username, email, password 
    FROM users 
    WHERE email = ? OR username = ?
    """,
    (user.identifier, user.identifier)
)
    db_user = cursor.fetchone()

    conn.close()

    if not db_user:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password."
        )

    user_id, username, email, hashed_password = db_user

    if not verify_password(user.password, hashed_password):
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password."
        )

    response.set_cookie(
        key="user_id",
        value=str(user_id),
        httponly=True,
        samesite="lax"
    )

    return {
        "message": "Login successful.",
        "user": {
            "id": user_id,
            "username": username,
            "email": email
        }
    }


@app.post("/logout")
def logout_user(response: Response):
    response.delete_cookie("user_id")
    return {"message": "Logged out successfully."}


@app.get("/me")
def get_current_user(request: Request):
    user_id = request.cookies.get("user_id")

    if not user_id:
        raise HTTPException(status_code=401, detail="Not logged in.")

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, username, email FROM users WHERE id = ?",
        (user_id,)
    )
    user = cursor.fetchone()

    conn.close()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid session.")

    return {
        "id": user[0],
        "username": user[1],
        "email": user[2]
    }


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