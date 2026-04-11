"""Runtime configuration loading and validation for LaunchMind ShiftSwap."""

import os
from dataclasses import dataclass
from typing import List

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Config:
    """Holds all required runtime configuration values."""

    openai_api_key: str
    github_token: str
    github_repo: str
    slack_bot_token: str
    brevo_api_key: str
    test_email: str
    verified_sender_email: str
    openai_model: str
    slack_channel: str


def _get_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    return value


def validate_config() -> Config:
    """Validate environment variables and return a strongly-typed config object."""
    required_keys: List[str] = [
        "OPENAI_API_KEY",
        "GITHUB_TOKEN",
        "GITHUB_REPO",
        "SLACK_BOT_TOKEN",
        "BREVO_API_KEY",
        "TEST_EMAIL",
        "VERIFIED_SENDER_EMAIL",
    ]

    missing_keys = [key for key in required_keys if not _get_env(key)]
    if missing_keys:
        missing_text = ", ".join(missing_keys)
        raise EnvironmentError(
            f"Missing required environment variables: {missing_text}. "
            "Update your .env file before running the system."
        )

    return Config(
        openai_api_key=_get_env("OPENAI_API_KEY"),
        github_token=_get_env("GITHUB_TOKEN"),
        github_repo=_get_env("GITHUB_REPO"),
        slack_bot_token=_get_env("SLACK_BOT_TOKEN"),
        brevo_api_key=_get_env("BREVO_API_KEY"),
        test_email=_get_env("TEST_EMAIL"),
        verified_sender_email=_get_env("VERIFIED_SENDER_EMAIL"),
        openai_model=_get_env("OPENAI_MODEL") or "gpt-4o-mini",
        slack_channel=_get_env("SLACK_CHANNEL") or "launches",
    )
