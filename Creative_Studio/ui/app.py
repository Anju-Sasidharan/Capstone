# Written by Anju for the Multi-Agent Creative Studio capstone (new file, not part
# of the original starter).
"""Streamlit UI for the deployed Creative Director (Vertex AI Agent Engine).

Run locally (from the repository root):
    uv add streamlit
    $env:PYTHONUTF8 = "1"
    uv run streamlit run app.py

It talks to the same deployed agent as chat_deployed.py. The agent call runs in
a background thread; the page polls a queue and shows which specialist is
working. Do not click or type while a campaign is running (a run takes about
10-15 minutes); the answer is still delivered when it finishes.
"""
import asyncio
import os
import queue
import re
import threading
import time

import streamlit as st
import vertexai
from dotenv import load_dotenv
from vertexai import agent_engines

load_dotenv()

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "")
LOCATION = os.getenv("CLOUD_RUN_REGION", "us-central1")
RESOURCE_NAME = os.getenv("AGENT_ENGINE_RESOURCE_NAME", "")
USER_ID = "ui_user"

EXAMPLE_BRIEF = (
    "Create a complete Instagram campaign for a handmade soy candle brand aimed at "
    "college students. Three posts. Product-only shots, no people, no text on the product."
)

STEP_LABELS = {
    "start_run": "Starting the run",
    "brand_strategist": "Brand Strategist: researching the market",
    "copywriter": "Copywriter: writing captions",
    "designer": "Designer: generating images",
    "critic": "Critic: reviewing the work",
    "project_manager": "Project Manager: building the timeline",
    "get_image_links": "Creating image links",
    "get_run_state": "Recovering the run details",
    "read_context": "Reading the saved results",
}

_IMAGE_URL = re.compile(r"\]\((https://storage\.googleapis\.com/[^)\s]+\.(?:png|jpg|jpeg|webp)[^)\s]*)\)")


# ---------- small pure helpers (unit-tested) ----------
def step_label(tool_name: str) -> str:
    return STEP_LABELS.get(tool_name, f"Working: {tool_name}")


def extract_image_urls(text: str) -> list:
    """Signed image links in a markdown report, in order, without duplicates."""
    seen, urls = set(), []
    for url in _IMAGE_URL.findall(text or ""):
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def needs_decision(text: str) -> bool:
    """True when the agent is asking 'another round' or 'proceed'."""
    low = (text or "").lower()
    return "another round" in low and "proceed" in low and "?" in low


# ---------- agent access ----------
async def _stream_turn(session_id: str, message: str, out: "queue.Queue", create: bool):
    vertexai.init(project=PROJECT_ID, location=LOCATION)
    remote = agent_engines.get(RESOURCE_NAME)
    if create:
        session = await remote.async_create_session(user_id=USER_ID)
        session_id = session["id"]
        out.put(("session", session_id))
    async for event in remote.async_stream_query(
        user_id=USER_ID, session_id=session_id, message=message
    ):
        for part in (event.get("content") or {}).get("parts") or []:
            call = part.get("function_call")
            if call:
                out.put(("tool", call.get("name", "")))
            elif part.get("text"):
                out.put(("text", part["text"]))


def _worker(session_id, message, out, create):
    try:
        asyncio.run(_stream_turn(session_id, message, out, create))
        out.put(("done", ""))
    except Exception as exc:  # connection reset, auth, quota...
        out.put(("error", f"{type(exc).__name__}: {str(exc)[:300]}"))


def start_turn(message: str):
    """Start one turn in a background thread; returns the queue to poll."""
    out = queue.Queue()
    create = not st.session_state.session_id
    threading.Thread(
        target=_worker, args=(st.session_state.session_id, message, out, create), daemon=True
    ).start()
    return out


# ---------- page ----------
def init_state():
    st.session_state.setdefault("session_id", "")
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("pending", "")


def render_history():
    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            urls = extract_image_urls(m["content"]) if m["role"] == "assistant" else []
            if urls:
                cols = st.columns(len(urls))
                for col, url in zip(cols, urls):
                    col.image(url, width="stretch")


def run_turn(message: str):
    st.session_state.messages.append({"role": "user", "content": message})
    with st.chat_message("user"):
        st.markdown(message)

    out = start_turn(message)
    texts, steps, error = [], [], ""
    with st.chat_message("assistant"):
        status = st.status("Working on your campaign...", expanded=True)
        while True:
            try:
                kind, value = out.get(timeout=1)
            except queue.Empty:
                continue
            if kind == "session":
                st.session_state.session_id = value
            elif kind == "tool":
                steps.append(step_label(value))
                status.write(steps[-1])
                status.update(label=steps[-1])
            elif kind == "text":
                texts.append(value)
            elif kind == "error":
                error = value
                break
            elif kind == "done":
                break
        reply = "\n\n".join(t.strip() for t in texts if t.strip())
        if error:
            status.update(label="Connection problem", state="error", expanded=False)
            reply = (reply + "\n\n" if reply else "") + (
                f"**Connection lost** ({error}). The session is kept on the server "
                "(id in the sidebar). Send a short message such as 'please finish the "
                "report' to continue."
            )
        else:
            status.update(label="Done", state="complete", expanded=False)
        st.markdown(reply or "_(no text returned)_")
    st.session_state.messages.append({"role": "assistant", "content": reply})
    st.rerun()


def main():
    st.set_page_config(page_title="Creative Studio", page_icon="🎨", layout="centered")
    st.title("Multi-Agent Creative Studio")
    st.caption(
        "Describe a campaign idea. Six agents research, write, design, review and plan it. "
        "A full run takes about 10-15 minutes. Please do not click while it runs."
    )
    init_state()

    if not (PROJECT_ID and RESOURCE_NAME):
        st.error("Set GOOGLE_CLOUD_PROJECT and AGENT_ENGINE_RESOURCE_NAME (see .env).")
        return

    with st.sidebar:
        st.subheader("Session")
        st.code(st.session_state.session_id or "(not started)")
        if st.button("New campaign"):
            st.session_state.session_id = ""
            st.session_state.messages = []
            st.rerun()
        if not st.session_state.messages and st.button("Use example brief"):
            st.session_state.pending = EXAMPLE_BRIEF
            st.rerun()

    render_history()

    last = st.session_state.messages[-1] if st.session_state.messages else None
    if last and last["role"] == "assistant" and needs_decision(last["content"]):
        c1, c2 = st.columns(2)
        if c1.button("Another round", width="stretch"):
            st.session_state.pending = "another round"
            st.rerun()
        if c2.button("Proceed", width="stretch"):
            st.session_state.pending = "proceed"
            st.rerun()

    prompt = st.chat_input("Describe your campaign idea, or answer the Creative Director")
    message = st.session_state.pending or prompt
    if st.session_state.pending:
        st.session_state.pending = ""
    if message:
        run_turn(message)


main()
