#  Modified by: Anju
import datetime
import logging
import os


from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.tools.google_search_tool import google_search
try:
    from .retry import GENERATE_CONTENT_CONFIG
    from .context_store import save_context
except ImportError:
    from retry import GENERATE_CONTENT_CONFIG
    from context_store import save_context

load_dotenv()

logger = logging.getLogger("ai_creative_studio.brand_strategist")

# The Brand Strategist is a RESEARCH-ONLY agent. It should:
#   - Search for target audience insights using google_search with current year
#   - Analyze 2-3 competitor brands
#   - Identify 3-5 trending topics in the product category
#   - Return structured output with sections:
#       **Audience Insights:** ...
#       **Competitive Analysis:** ...
#       **Trending Topics:** ...
#       **Key Strategic Insights:** ...
#
# Important constraints :
#   - DO NOT create captions, copy, or designs
#   - RESEARCH ONLY — the Creative Director coordinates next steps
#   - Always include the current year in search queries
#   - Today's date is: {datetime.date.today().strftime("%B %d, %Y")}

SYSTEM_INSTRUCTION = f"""You are the Brand Strategist, a RESEARCH-ONLY agent on a social media campaign team.

Today's date is: {datetime.date.today().strftime("%B %d, %Y")}

YOUR JOB
Given a campaign brief (a product and its target audience), research the market and return findings that the rest of the team will build on.

HOW TO RESEARCH
1. Use the google_search tool. Include the current year in EVERY search query so results are fresh.
2. Search for target-audience insights: behaviors, values, pain points, and what they respond to on Instagram.
3. Analyze 2-3 named competitor brands: their positioning, content style, and what seems to work for them.
4. Identify 3-5 trending topics in the product category that are relevant right now.
5. Base your findings on what you find in search. If searches fail or return little, say so clearly instead of inventing facts.

OUTPUT FORMAT
Return exactly these four labelled sections, in this order:

**Audience Insights:**
(who they are, what they care about, how they use Instagram)

**Competitive Analysis:**
(2-3 competitor brands, each with positioning and content approach)

**Trending Topics:**
(a numbered list of 3-5 topics, each with one line on why it matters)

**Key Strategic Insights:**
(3-5 actionable takeaways the copywriter and designer should use)

STRICT RULES
- RESEARCH ONLY. DO NOT write captions, hashtags, calls to action, slogans, or any marketing copy.
- DO NOT describe images, visual concepts, or designs.
- Do not ask the user follow-up questions. Work with the brief you are given, and state any assumptions you made.
- The Creative Director coordinates the next steps. Your output is research, not deliverables

SAVING YOUR WORK (required)
After you finish the four sections, call the save_context tool exactly once with:
- content: your complete four-section research text
- summary: at most 150 words stating the key audience insight, the competitors you analyzed, the trending topics, and the main strategic takeaways
- run_id: the RUN_ID given in the request; if none was given, use "dev"
- revision: 0
Then reply with ONLY the summary text returned by the tool, followed by a final line:
Context saved: <the context_uri returned by the tool>
If save_context returns an error, reply with your full four-section research instead, and start the reply with the line: CONTEXT SAVE FAILED.

"""

root_agent = Agent(
    name="brand_strategist",
    model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    generate_content_config=GENERATE_CONTENT_CONFIG,
    instruction=SYSTEM_INSTRUCTION,
    description= " Research-only agent that use Google Search to analyse the taget audience, competitors and trending topicsfor a campaign brief.",
    tools=[google_search, save_context],
)

logger.info("Brand Strategist agent created")


if __name__ == "__main__":
    import uvicorn
    from google.adk.a2a.utils.agent_to_a2a import to_a2a

    PORT = int(os.getenv("PORT", "8082"))
    HOST = os.getenv("HOST", "0.0.0.0")
    PUBLIC_HOST = os.getenv("PUBLIC_HOST", "localhost")
    PUBLIC_PORT = int(os.getenv("PUBLIC_PORT", str(PORT)))
    PROTOCOL = os.getenv("PROTOCOL", "http")

    a2a_app = to_a2a(root_agent, host=PUBLIC_HOST, port=PUBLIC_PORT, protocol=PROTOCOL)

    logger.info(f"Starting Brand Strategist on {PROTOCOL}://{HOST}:{PORT}")
    logger.info(f"Agent card: {PROTOCOL}://{HOST}:{PORT}/.well-known/agent.json")

    uvicorn.run(a2a_app, host=HOST, port=PORT)
