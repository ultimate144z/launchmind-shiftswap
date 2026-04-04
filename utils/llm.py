"""Shared OpenAI LLM utility wrapper."""

import os
from typing import Optional

from openai import OpenAI


def call_llm(system_prompt: str, user_prompt: str, response_format: str = "text") -> str:
    """Call OpenAI chat completions and return assistant content."""
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    request: dict = {
        "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    if response_format == "json":
        request["response_format"] = {"type": "json_object"}

    response = client.chat.completions.create(**request)
    content: Optional[str] = response.choices[0].message.content
    return content or ""
