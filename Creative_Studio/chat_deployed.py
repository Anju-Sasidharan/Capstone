# Written by Anju for the Multi-Agent Creative Studio capstone (new file, not part
# of the original starter).
"""Interactive chat with the deployed Creative Director on Agent Engine.

Keeps one session open, so you can answer the Creative Director's questions
("another round" or "proceed") after the first message. If the connection
drops, the session stays on the server: run again with --session <id>.

Usage (from the repository root):
    $env:PYTHONUTF8 = "1"
    uv run python chat_deployed.py
    uv run python chat_deployed.py "Create a campaign for ..."      # first message
    uv run python chat_deployed.py --session <id>                   # resume a session
Type  quit  to leave.
"""
import argparse
import asyncio
import os
import sys

import vertexai
from dotenv import load_dotenv
from vertexai import agent_engines

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

load_dotenv()

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "")
LOCATION = os.getenv("CLOUD_RUN_REGION", "us-central1")
RESOURCE_NAME = os.getenv("AGENT_ENGINE_RESOURCE_NAME", "")

DEFAULT_BRIEF = (
    "Create a complete Instagram campaign for a smart water bottle that tracks "
    "hydration, aimed at health-conscious millennials. Three posts. "
    "Product-only shots, no people, no text on the product."
)


async def send(remote_app, session_id: str, message: str) -> None:
    """Send one message and print the agent's text and tool calls.

    A dropped connection is reported, not raised, so the chat stays open.
    """
    try:
        async for event in remote_app.async_stream_query(
            user_id="chat_user", session_id=session_id, message=message
        ):
            for part in (event.get("content") or {}).get("parts") or []:
                call = part.get("function_call")
                if call:
                    print(f"  [tool] {call.get('name')}")
                elif part.get("text"):
                    print(part["text"])
    except Exception as exc:  # connection reset, sleep, VPN, etc.
        print(
            f"\n[connection lost: {type(exc).__name__}] The session is kept on the "
            f"server. Session id: {session_id}\n"
            "Type a short message such as 'please finish the report' to try again, "
            "or 'quit' and run again with --session <id>."
        )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("message", nargs="*", help="first message (optional)")
    parser.add_argument("--session", help="resume this session id instead of starting a new one")
    args = parser.parse_args()

    if not (PROJECT_ID and RESOURCE_NAME):
        print("Set GOOGLE_CLOUD_PROJECT and AGENT_ENGINE_RESOURCE_NAME in .env first.")
        return
    vertexai.init(project=PROJECT_ID, location=LOCATION)
    remote_app = agent_engines.get(RESOURCE_NAME)

    if args.session:
        session_id = args.session
        print(f"Resuming session {session_id}. Type 'quit' to leave.\n")
        first = " ".join(args.message).strip()
    else:
        session = await remote_app.async_create_session(user_id="chat_user")
        session_id = session["id"]
        print(f"Connected. Session {session_id}. Type 'quit' to leave.\n")
        first = " ".join(args.message).strip() or DEFAULT_BRIEF

    if first:
        print(f"YOU: {first}\n")
        await send(remote_app, session_id, first)

    while True:
        try:
            message = await asyncio.to_thread(input, "\nYOU: ")
        except (EOFError, KeyboardInterrupt):
            break
        if message.strip().lower() in ("quit", "exit", ""):
            break
        print()
        await send(remote_app, session_id, message)


if __name__ == "__main__":
    asyncio.run(main())
