"""Load explicitly supported local secrets from PathForge's ignored .env file."""

import os
from pathlib import Path


SUPPORTED_LOCAL_ENVIRONMENT = {
    "CAREERONESTOP_API_TOKEN",
    "CAREERONESTOP_USER_ID",
    "USAJOBS_API_KEY",
    "USAJOBS_USER_AGENT",
    "RESEND_API_KEY",
    "PATHFORGE_FROM_EMAIL",
}


def load_local_environment(path=None):
    environment_path = Path(path or Path(__file__).resolve().parent / ".env")
    if not environment_path.is_file():
        return 0
    loaded = 0
    for raw_line in environment_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name not in SUPPORTED_LOCAL_ENVIRONMENT or name in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if value:
            os.environ[name] = value
            loaded += 1
    return loaded
