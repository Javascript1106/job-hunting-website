"""Privately configure local USAJOBS credentials for manual synchronization."""

import getpass
from pathlib import Path


def configure_usajobs(environment_path=None):
    path = Path(environment_path or Path(__file__).resolve().parent / ".env")
    api_key = getpass.getpass("USAJOBS API key (input hidden): ").strip()
    user_agent = input("USAJOBS registered email: ").strip()
    if not api_key or not user_agent or "@" not in user_agent:
        raise ValueError("A non-empty API key and valid registered email are required.")

    retained = []
    if path.exists():
        retained = [
            line for line in path.read_text(encoding="utf-8").splitlines()
            if not line.strip().startswith(("USAJOBS_API_KEY=", "USAJOBS_USER_AGENT="))
        ]
    retained.extend([
        "USAJOBS_API_KEY=" + api_key,
        "USAJOBS_USER_AGENT=" + user_agent,
    ])
    path.write_text("\n".join(retained).strip() + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    configured = configure_usajobs()
    print(f"USAJOBS credentials saved privately in {configured}")
    print("The .env file is excluded from Git.")
