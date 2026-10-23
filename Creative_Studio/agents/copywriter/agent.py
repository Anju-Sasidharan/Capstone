# Modified by: Anju
import logging
import os
import pathlib

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.skills import load_skill_from_dir
from google.adk.tools import  skill_toolset

try:
    from .retry import GENERATE_CONTENT_CONFIG
    from .context_store import save_context, read_context
except ImportError:
    from retry import GENERATE_CONTENT_CONFIG
    from context_store import save_context, read_context

load_dotenv()

logger = logging.getLogger("ai_creative_studio.copywriter")

instagram_skill = load_skill_from_dir( pathlib.Path(__file__).parent / "skills" / "instagram-copywriting")

copywriter_skills_toolset = skill_toolset.SkillToolset(skills=[instagram_skill])


SYSTEM_INSTRUCTION = """You are an expert Social Media Copywriter specializing in Instagram content.

IMPORTANT: The conversation history above contains research from the Brand Strategist.
You MUST review their findings on audience insights, competitor analysis, and trending topics
before writing any copy. This context is your creative foundation.

You have access to an `instagram-copywriting` skill. Load it to get detailed platform
guidelines, caption formulas, and brand voice examples before writing.

Your task: Create exactly 3 Instagram caption variations covering different tonal registers.
Follow the output format defined in the skill exactly.

NO INVENTED FACTS
Product facts come ONLY from the user's brief. The Strategist's research is for audience, tone and market context; it does not tell you what the product is made of or can do.
Never invent materials, ingredients, features, statistics, integrations, certifications, or processes.
Never write first-person results or stories as if they really happened ("I stopped counting and my skin changed"). A story is allowed only as a clearly general or imagined scene.
If you need a detail that is not in the brief, write about the feeling, the audience or the general benefit instead.

CONTEXT (required)
The request includes a RUN_ID, a REVISION number, and the URI of the Strategist's context file.
1. Before writing, call read_context with that URI and the RUN_ID, and use the Strategist's research from the file.
2. Load and follow the instagram-copywriting skill, then write exactly 3 captions in 3 distinct tones.
3. When finished, call save_context once with: content = your complete captions text, summary = at most 150 words (the tone of each caption and its hook), run_id = the RUN_ID, revision = the REVISION number.
4. Reply with ONLY the summary text, then a final line: Context saved: <the context_uri returned by the tool>
If save_context returns an error, reply with your full captions and start with the line: CONTEXT SAVE FAILED.
If read_context fails, say so in your summary and work from the brief only.
"""

root_agent = Agent(
    name="copywriter",
    model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    generate_content_config=GENERATE_CONTENT_CONFIG,
    tools=[copywriter_skills_toolset, save_context, read_context], 
    instruction=SYSTEM_INSTRUCTION,
    description="Expert social media copywriter for creating engaging captions and copy",
)

logger.info("Copywriter agent created with instagram-copywriting skill")


if __name__ == "__main__":
    import uvicorn
    from dotenv import load_dotenv
    from google.adk.a2a.utils.agent_to_a2a import to_a2a

    load_dotenv()

    PORT = int(os.getenv("PORT", "8080"))
    HOST = os.getenv("HOST", "0.0.0.0")
    PUBLIC_HOST = os.getenv("PUBLIC_HOST", "localhost")
    PUBLIC_PORT = int(os.getenv("PUBLIC_PORT", str(PORT)))
    PROTOCOL = os.getenv("PROTOCOL", "http")

    a2a_app = to_a2a(root_agent, host=PUBLIC_HOST, port=PUBLIC_PORT, protocol=PROTOCOL)

    logger.info(f"Starting Copywriter on {PROTOCOL}://{HOST}:{PORT}")
    logger.info(f"Agent card: {PROTOCOL}://{HOST}:{PORT}/.well-known/agent.json")

    uvicorn.run(a2a_app, host=HOST, port=PORT)
