from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from datetime import datetime, timezone
from typing import Optional
import hashlib
import hmac
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
    try:
        salt, saved_hash = stored_password.split(":", 1)
    except ValueError:
        return False

    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        plain_password.encode("utf-8"),
        salt.encode("utf-8"),
        100000
    ).hex()

    return hmac.compare_digest(password_hash, saved_hash)

def hash_access_code(code: str):
    normalized_code = code.strip().upper()

    return hashlib.sha256(
        normalized_code.encode("utf-8")
    ).hexdigest()

def get_authenticated_user(request: Request):
    user_id = request.cookies.get("user_id")

    if not user_id or not user_id.isdigit():
        raise HTTPException(
            status_code=401,
            detail="Not logged in."
        )

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, username, email, role
        FROM users
        WHERE id = ?
        """,
        (int(user_id),)
    )

    user = cursor.fetchone()
    conn.close()

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid session."
        )

    return dict(user)


def require_employer(request: Request):
    user = get_authenticated_user(request)

    if user["role"] != "employer":
        raise HTTPException(
            status_code=403,
            detail="Employer access is required."
        )

    return user

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
    application_method: str = "pathforge"
    application_url: Optional[str] = None


class RegisterUser(BaseModel):
    username: str
    email: EmailStr
    password: str


class LoginUser(BaseModel):
    identifier: str
    password: str

class EmployerCodeRedemption(BaseModel):
    code: str

class UserProfileUpdate(BaseModel):
    display_name: Optional[str] = None
    career_interests: Optional[str] = None
    preferred_industries: Optional[str] = None
    skills: Optional[str] = None
    experience_level: Optional[str] = None
    preferred_location: Optional[str] = None
    schedule_preference: Optional[str] = None
    work_preference: Optional[str] = None
    desired_pay: Optional[str] = None
    career_goals: Optional[str] = None

class ApplicationCreate(BaseModel):
    job_id: int
    application_method: str
    status: str = "Interested"
    applied_at: Optional[str] = None
    interview_date: Optional[str] = None
    follow_up_date: Optional[str] = None
    notes: Optional[str] = None


class ApplicationUpdate(BaseModel):
    status: Optional[str] = None
    applied_at: Optional[str] = None
    interview_date: Optional[str] = None
    follow_up_date: Optional[str] = None
    notes: Optional[str] = None

APPLICATION_METHODS = {
    "pathforge",
    "employer_website"
}

APPLICATION_STATUSES = {
    "Interested",
    "Applied",
    "Application Viewed",
    "Under Review",
    "Interview Scheduled",
    "Interview Completed",
    "Offer Extended",
    "Accepted",
    "Rejected",
    "Withdrawn"
}

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
def add_job(job: Job, request: Request):
    require_employer(request)

    if job.application_method not in APPLICATION_METHODS:
        raise HTTPException(
        status_code=400,
        detail="Invalid application method."
        )

    cleaned_application_url = (
        job.application_url.strip()
        if job.application_url
        else None
    )

    if (
        job.application_method == "employer_website"
        and not cleaned_application_url
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "An employer application URL is required "
                "for employer-website jobs."
            )
        )

    if job.application_method == "pathforge":
        cleaned_application_url = None

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
            category,
            application_method,
            application_url
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        job.title,
        job.company,
        job.location,
        job.pay,
        job.description,
        job.schedule,
        job.experience,
        job.category,
        job.application_method,
        cleaned_application_url
    ))

    conn.commit()
    conn.close()

    return {"message": "Job added successfully"}


@app.delete("/jobs/{job_id}")
def delete_job(job_id: int, request: Request):
    require_employer(request)

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM jobs WHERE id = ?",
        (job_id,)
    )

    conn.commit()
    conn.close()

    return {
        "message": f"Job {job_id} deleted successfully"
    }

@app.get("/saved-jobs")
def get_saved_jobs(request: Request):
    user = get_authenticated_user(request)

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            jobs.id,
            jobs.title,
            jobs.company,
            jobs.location,
            jobs.pay,
            jobs.description,
            jobs.schedule,
            jobs.experience,
            jobs.category,
            saved_jobs.saved_at
        FROM saved_jobs
        JOIN jobs
            ON jobs.id = saved_jobs.job_id
        WHERE saved_jobs.user_id = ?
        ORDER BY saved_jobs.saved_at DESC
        """,
        (user["id"],)
    )

    saved_jobs = [
        dict(row)
        for row in cursor.fetchall()
    ]

    conn.close()

    return {
        "saved_jobs": saved_jobs
    }


@app.post("/saved-jobs/{job_id}")
def save_job(job_id: int, request: Request):
    user = get_authenticated_user(request)

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id
        FROM jobs
        WHERE id = ?
        """,
        (job_id,)
    )

    job = cursor.fetchone()

    if not job:
        conn.close()

        raise HTTPException(
            status_code=404,
            detail="Job not found."
        )

    try:
        cursor.execute(
            """
            INSERT INTO saved_jobs (
                user_id,
                job_id
            )
            VALUES (?, ?)
            """,
            (
                user["id"],
                job_id
            )
        )

        conn.commit()

    except sqlite3.IntegrityError:
        conn.close()

        return {
            "message": "This job is already saved.",
            "already_saved": True
        }

    conn.close()

    return {
        "message": "Job saved successfully.",
        "already_saved": False
    }

@app.get("/applications")
def get_applications(request: Request):
    user = get_authenticated_user(request)

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            applications.id,
            applications.job_id,
            applications.application_method,
            applications.status,
            applications.applied_at,
            applications.interview_date,
            applications.follow_up_date,
            applications.notes,
            applications.created_at,
            applications.updated_at,
            jobs.title,
            jobs.company,
            jobs.location,
            jobs.pay,
            jobs.schedule,
            jobs.experience,
            jobs.category
        FROM applications
        JOIN jobs
            ON jobs.id = applications.job_id
        WHERE applications.user_id = ?
        ORDER BY applications.updated_at DESC
        """,
        (user["id"],)
    )

    applications = [
        dict(row)
        for row in cursor.fetchall()
    ]

    conn.close()

    return {
        "applications": applications
    }


@app.post("/applications")
def create_application(
    application: ApplicationCreate,
    request: Request
):
    user = get_authenticated_user(request)

    if application.application_method not in APPLICATION_METHODS:
        raise HTTPException(
            status_code=400,
            detail="Invalid application method."
        )

    if application.status not in APPLICATION_STATUSES:
        raise HTTPException(
            status_code=400,
            detail="Invalid application status."
        )

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id
        FROM jobs
        WHERE id = ?
        """,
        (application.job_id,)
    )

    job = cursor.fetchone()

    if not job:
        conn.close()

        raise HTTPException(
            status_code=404,
            detail="Job not found."
        )

    try:
        cursor.execute(
            """
            INSERT INTO applications (
                user_id,
                job_id,
                application_method,
                status,
                applied_at,
                interview_date,
                follow_up_date,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user["id"],
                application.job_id,
                application.application_method,
                application.status,
                application.applied_at,
                application.interview_date,
                application.follow_up_date,
                application.notes
            )
        )

        application_id = cursor.lastrowid
        conn.commit()

    except sqlite3.IntegrityError:
        conn.close()

        raise HTTPException(
            status_code=409,
            detail="This job is already in your Application Tracker."
        )

    conn.close()

    return {
        "message": "Application added to your tracker.",
        "application_id": application_id
    }


@app.put("/applications/{application_id}")
def update_application(
    application_id: int,
    application: ApplicationUpdate,
    request: Request
):
    user = get_authenticated_user(request)

    if (
        application.status is not None
        and application.status not in APPLICATION_STATUSES
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid application status."
        )

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM applications
        WHERE id = ?
          AND user_id = ?
        """,
        (
            application_id,
            user["id"]
        )
    )

    existing_application = cursor.fetchone()

    if not existing_application:
        conn.close()

        raise HTTPException(
            status_code=404,
            detail="Application not found."
        )

    updated_status = (
        application.status
        if application.status is not None
        else existing_application["status"]
    )

    updated_applied_at = (
        application.applied_at
        if application.applied_at is not None
        else existing_application["applied_at"]
    )

    updated_interview_date = (
        application.interview_date
        if application.interview_date is not None
        else existing_application["interview_date"]
    )

    updated_follow_up_date = (
        application.follow_up_date
        if application.follow_up_date is not None
        else existing_application["follow_up_date"]
    )

    updated_notes = (
        application.notes
        if application.notes is not None
        else existing_application["notes"]
    )

    cursor.execute(
        """
        UPDATE applications
        SET
            status = ?,
            applied_at = ?,
            interview_date = ?,
            follow_up_date = ?,
            notes = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
          AND user_id = ?
        """,
        (
            updated_status,
            updated_applied_at,
            updated_interview_date,
            updated_follow_up_date,
            updated_notes,
            application_id,
            user["id"]
        )
    )

    conn.commit()
    conn.close()

    return {
        "message": "Application updated successfully."
    }


@app.delete("/applications/{application_id}")
def delete_application(
    application_id: int,
    request: Request
):
    user = get_authenticated_user(request)

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        DELETE FROM applications
        WHERE id = ?
          AND user_id = ?
        """,
        (
            application_id,
            user["id"]
        )
    )

    removed = cursor.rowcount
    conn.commit()
    conn.close()

    if removed == 0:
        raise HTTPException(
            status_code=404,
            detail="Application not found."
        )

    return {
        "message": "Application removed from your tracker."
    }

@app.delete("/saved-jobs/{job_id}")
def remove_saved_job(job_id: int, request: Request):
    user = get_authenticated_user(request)

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        DELETE FROM saved_jobs
        WHERE user_id = ?
          AND job_id = ?
        """,
        (
            user["id"],
            job_id
        )
    )

    removed = cursor.rowcount
    conn.commit()
    conn.close()

    if removed == 0:
        raise HTTPException(
            status_code=404,
            detail="Saved job not found."
        )

    return {
        "message": "Job removed from saved jobs."
    }




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
    """
    INSERT INTO users (
        username,
        email,
        password,
        role
    )
    VALUES (?, ?, ?, 'job_seeker')
    """,
    (
        user.username,
        user.email,
        hashed_password
    )
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
    SELECT id, username, email, password, role
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

    user_id, username, email, hashed_password, role = db_user

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
            "email": email,
            "role": role
        }
    }


@app.post("/logout")
def logout_user(response: Response):
    response.delete_cookie("user_id")
    return {"message": "Logged out successfully."}


@app.get("/me")
def get_current_user(request: Request):
    return get_authenticated_user(request)


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

@app.get("/profile")
def get_user_profile(request: Request):
    user = get_authenticated_user(request)

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            display_name,
            career_interests,
            preferred_industries,
            skills,
            experience_level,
            preferred_location,
            schedule_preference,
            work_preference,
            desired_pay,
            career_goals,
            created_at,
            updated_at
        FROM user_profiles
        WHERE user_id = ?
        """,
        (user["id"],)
    )

    profile = cursor.fetchone()
    conn.close()

    if not profile:
        return {
            "user": user,
            "profile": {
                "display_name": "",
                "career_interests": "",
                "preferred_industries": "",
                "skills": "",
                "experience_level": "",
                "preferred_location": "",
                "schedule_preference": "",
                "work_preference": "",
                "desired_pay": "",
                "career_goals": ""
            }
        }

    return {
        "user": user,
        "profile": dict(profile)
    }

@app.put("/profile")
def update_user_profile(
    profile: UserProfileUpdate,
    request: Request
):
    user = get_authenticated_user(request)

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO user_profiles (
            user_id,
            display_name,
            career_interests,
            preferred_industries,
            skills,
            experience_level,
            preferred_location,
            schedule_preference,
            work_preference,
            desired_pay,
            career_goals
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

        ON CONFLICT(user_id) DO UPDATE SET
            display_name = excluded.display_name,
            career_interests = excluded.career_interests,
            preferred_industries = excluded.preferred_industries,
            skills = excluded.skills,
            experience_level = excluded.experience_level,
            preferred_location = excluded.preferred_location,
            schedule_preference = excluded.schedule_preference,
            work_preference = excluded.work_preference,
            desired_pay = excluded.desired_pay,
            career_goals = excluded.career_goals,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            user["id"],
            profile.display_name,
            profile.career_interests,
            profile.preferred_industries,
            profile.skills,
            profile.experience_level,
            profile.preferred_location,
            profile.schedule_preference,
            profile.work_preference,
            profile.desired_pay,
            profile.career_goals
        )
    )

    conn.commit()
    conn.close()

    return {
        "message": "Profile saved successfully."
    }

@app.post("/employer-access/redeem")
def redeem_employer_access_code(
    redemption: EmployerCodeRedemption,
    request: Request
):
    user = get_authenticated_user(request)
    submitted_code = redemption.code.strip()

    if not submitted_code:
        raise HTTPException(
            status_code=400,
            detail="Enter an employer access code."
        )

    if user["role"] == "employer":
        return {
            "message": "Your account already has employer access.",
            "role": "employer"
        }

    code_hash = hash_access_code(submitted_code)
    current_time = datetime.now(timezone.utc)

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row

    try:
        cursor = conn.cursor()

        cursor.execute("BEGIN IMMEDIATE")

        cursor.execute(
            """
            SELECT
                id,
                is_used,
                expires_at,
                company_name
            FROM employer_access_codes
            WHERE code_hash = ?
            """,
            (code_hash,)
        )

        access_code = cursor.fetchone()

        if not access_code:
            conn.rollback()

            raise HTTPException(
                status_code=400,
                detail="That employer access code is invalid."
            )

        if access_code["is_used"]:
            conn.rollback()

            raise HTTPException(
                status_code=400,
                detail="That employer access code has already been redeemed."
            )

        if access_code["expires_at"]:
            try:
                expiration = datetime.fromisoformat(
                    access_code["expires_at"].replace(
                        "Z",
                        "+00:00"
                    )
                )

                if expiration.tzinfo is None:
                    expiration = expiration.replace(
                        tzinfo=timezone.utc
                    )

            except ValueError:
                conn.rollback()

                raise HTTPException(
                    status_code=500,
                    detail="The access code has an invalid expiration date."
                )

            if expiration <= current_time:
                conn.rollback()

                raise HTTPException(
                    status_code=400,
                    detail="That employer access code has expired."
                )

        cursor.execute(
            """
            UPDATE users
            SET role = 'employer'
            WHERE id = ?
            """,
            (user["id"],)
        )

        cursor.execute(
            """
            UPDATE employer_access_codes
            SET
                is_used = 1,
                redeemed_by_user_id = ?,
                redeemed_at = ?
            WHERE id = ?
              AND is_used = 0
            """,
            (
                user["id"],
                current_time.isoformat(),
                access_code["id"]
            )
        )

        if cursor.rowcount != 1:
            conn.rollback()

            raise HTTPException(
                status_code=409,
                detail="That access code was just redeemed by another account."
            )

        conn.commit()

    except HTTPException:
        raise

    except sqlite3.Error:
        conn.rollback()

        raise HTTPException(
            status_code=500,
            detail="The employer access request could not be completed."
        )

    finally:
        conn.close()

    return {
        "message": "Employer access approved successfully.",
        "role": "employer",
        "company_name": access_code["company_name"]
    }


@app.get("/dashboard-summary")
def get_dashboard_summary(request: Request):
    user = get_authenticated_user(request)

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM saved_jobs
        WHERE user_id = ?
        """,
        (user["id"],)
    )

    saved_jobs_count = cursor.fetchone()[0]

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM applications
        WHERE user_id = ?
          AND status NOT IN (
              'Accepted',
              'Rejected',
              'Withdrawn'
          )
        """,
        (user["id"],)
    )

    applications_count = cursor.fetchone()[0]

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM applications
        WHERE user_id = ?
          AND status = 'Interview Scheduled'
          AND interview_date IS NOT NULL
          AND interview_date != ''
        """,
        (user["id"],)
    )

    interviews_count = cursor.fetchone()[0]

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM applications
        WHERE user_id = ?
          AND follow_up_date IS NOT NULL
          AND follow_up_date != ''
          AND substr(follow_up_date, 1, 10) <= date('now')
          AND status NOT IN (
              'Accepted',
              'Rejected',
              'Withdrawn'
          )
        """,
        (user["id"],)
    )

    follow_ups_count = cursor.fetchone()[0]

    conn.close()

    return {
        "user": {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "role": user["role"]
        },
        "summary": {
            "saved_jobs": saved_jobs_count,
            "applications": applications_count,
            "interviews": interviews_count,
            "follow_ups": follow_ups_count
        }
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