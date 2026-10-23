#  Modified by: Anju
import logging
import os

from google.adk.agents import Agent
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent
from google.adk.plugins.logging_plugin import LoggingPlugin
from google.adk.tools import FunctionTool
from google.adk.tools.agent_tool import AgentTool

try:
    from .retry import RETRY_CONFIG
    from .display_image_tool import display_image
    from .get_image_links_tool import get_image_links
    from .run_tools import start_run, read_context, get_run_state
    from .guardrails import input_guardrail, output_guardrail
except ImportError:
    from retry import RETRY_CONFIG
    from display_image_tool import display_image
    from get_image_links_tool import get_image_links
    from run_tools import start_run, read_context, get_run_state
    from guardrails import input_guardrail, output_guardrail

try:
    from .prompt import SYSTEM_INSTRUCTION_TEMPLATE
except ImportError:
    from prompt import SYSTEM_INSTRUCTION_TEMPLATE  # direct execution fallback

logger = logging.getLogger("ai_creative_studio.creative_director")
logger.setLevel(logging.INFO)


def create_creative_director():
    """
    Create the Creative Director orchestrator.
    Reads specialist URLs from environment variables at runtime.
    """
    # Read specialist URLs from environment
    copywriter_url = os.getenv("COPYWRITER_AGENT_URL")
    designer_url = os.getenv("DESIGNER_AGENT_URL")
    strategist_url = os.getenv("STRATEGIST_AGENT_URL")
    critic_url = os.getenv("CRITIC_AGENT_URL")
    pm_url = os.getenv("PM_AGENT_URL")

    available_agents_list = []
    agent_tools = [
        FunctionTool(func=display_image),
        FunctionTool(func=get_image_links),
        FunctionTool(func=start_run),
        FunctionTool(func=read_context),
        FunctionTool(func=get_run_state),
    ]

    specialists = [
        ("brand_strategist", strategist_url,
         "Researches market trends, competitors, and audience insights"),
        ("copywriter", copywriter_url,
         "Writes Instagram captions and hashtags"),
        ("designer", designer_url,
         "Generates image concepts and saves them to GCS"),
        ("critic", critic_url,
         "Reviews posts and visuals and returns a scored verdict"),
        ("project_manager", pm_url,
         "Builds the project timeline and deliverables"),
    ]

    for name, url, description in specialists:
        if not url:
            logger.warning("No URL set for %s, skipping", name)
            continue
        available_agents_list.append(f"- **{name}**: {description}")
        remote = RemoteA2aAgent(
            name=name,
            description=description,
            agent_card=f"{url.rstrip('/')}/.well-known/agent.json",
        )
        agent_tools.append(AgentTool(agent=remote))

   
    available_agents_text = (
        "\n".join(available_agents_list)
        if available_agents_list
        else "No specialist agents configured. Set agent URLs in environment variables."
    )

    system_instruction = SYSTEM_INSTRUCTION_TEMPLATE.format(
        available_agents=available_agents_text
    )

    from google.genai import types
    generation_config = types.GenerateContentConfig(
        max_output_tokens=20000,
        temperature=0.2,
        http_options=types.HttpOptions(
            retry_options=RETRY_CONFIG,
            timeout=120_000,  # 120 second timeout for model calls
        ),
    )

    agent = Agent(
        name="creative_director",
        model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        description="Creative Director orchestrator that coordinates specialist agents",
        instruction=system_instruction,
        tools=agent_tools,
        generate_content_config=generation_config,
        before_model_callback=input_guardrail,
        after_model_callback=output_guardrail,
    )

    from google.adk.apps import App
    from google.adk.apps.app import EventsCompactionConfig
    from google.adk.apps.llm_event_summarizer import LlmEventSummarizer
    from google.adk.models import Gemini

    compaction_config = EventsCompactionConfig(
        summarizer=LlmEventSummarizer(
            llm=Gemini(model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))
        ),
        compaction_interval=10,
        overlap_size=1,
    )
    app = App(
        name="creative_director",
        root_agent=agent,
        events_compaction_config=compaction_config,
        plugins=[LoggingPlugin()],
    )
    return agent, app


root_agent, root_app = create_creative_director()
