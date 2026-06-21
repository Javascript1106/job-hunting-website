from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import json

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatMessage(BaseModel):
    message: str

@app.get("/")
def home():
    return {"message": "Job hunting website backend is running"}

@app.get("/jobs")
def get_jobs():
    with open("jobs.json", "r") as file:
        jobs = json.load(file)

    return jobs

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