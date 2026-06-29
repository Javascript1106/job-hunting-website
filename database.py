import sqlite3
import json

DB_NAME = "jobs.db"

def create_jobs_table():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            company TEXT NOT NULL,
            location TEXT NOT NULL,
            pay TEXT NOT NULL,
            description TEXT NOT NULL,
            schedule TEXT NOT NULL,
            experience TEXT NOT NULL,
            category TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def populate_jobs():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Prevent duplicate inserts
    cursor.execute("SELECT COUNT(*) FROM jobs")
    count = cursor.fetchone()[0]

    if count == 0:
        with open("jobs.json", "r") as file:
            jobs = json.load(file)

        for job in jobs:
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
                job["title"],
                job["company"],
                job["location"],
                job["pay"],
                job["description"],
                job["schedule"],
                job["experience"],
                job["category"]
            ))

        print("Jobs inserted successfully.")
    else:
        print("Database already contains jobs.")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    create_jobs_table()
    populate_jobs()