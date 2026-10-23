# Written by Anju for the Multi-Agent Creative Studio capstone (new file, not part
# of the original starter).
"""One-time patch: adds the claim rules to the Critic and Copywriter instructions.

Run from the repository root:   python deploy/patch_claim_rules.py
Safe to run twice (it skips files that already have the rules).
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MARK = "CLAIM CHECK"
MARK_CW = "NO INVENTED FACTS"

CRITIC_BLOCK = """CLAIM CHECK (do this BEFORE scoring the posts):
For each caption, list every factual claim about the product: a feature, material, ingredient, process, statistic, integration, certification, result, or testimonial.
Product facts are supported ONLY by the user's original brief, if it appears in the request. The Strategist's research supports audience and market statements only; it does not prove what the product is or has.
Any product claim that the brief does not support is INVENTED. A first-person result or story presented as real ("my skin changed", "I saw...") is also invented.
If any caption has an invented claim: Status NEEDS_REVISION, POSTS score 6 or lower, put that caption's number in Failed Captions, and name the exact claim under Priority Revisions with the instruction: remove the claim and do not replace it with another invented one.
Opinions, tone, feelings and general benefits are fine.

"""

COPY_BLOCK = """NO INVENTED FACTS
Product facts come ONLY from the user's brief. The Strategist's research is for audience, tone and market context; it does not tell you what the product is made of or can do.
Never invent materials, ingredients, features, statistics, integrations, certifications, or processes.
Never write first-person results or stories as if they really happened ("I stopped counting and my skin changed"). A story is allowed only as a clearly general or imagined scene.
If you need a detail that is not in the brief, write about the feeling, the audience or the general benefit instead.

"""


def patch(path, anchor, block, mark, remove_pattern=None):
    text = path.read_text(encoding="utf-8")
    if mark in text:
        print(f"skip   {path.name}: already patched")
        return True
    if text.count(anchor) != 1:
        print(f"ERROR  {path.name}: anchor {anchor!r} found {text.count(anchor)} times")
        return False
    if remove_pattern:
        text, n = re.subn(remove_pattern, "", text, flags=re.DOTALL)
        print(f"       removed old one-sentence rule: {n} match(es)")
    text = text.replace(anchor, block + anchor, 1)
    path.write_text(text, encoding="utf-8", newline="")
    print(f"patched {path.name}")
    return True


ok = patch(
    ROOT / "agents" / "critic" / "agent.py",
    "APPROVAL RULE:",
    CRITIC_BLOCK,
    MARK,
    remove_pattern=r"\s*Also give\s*NEEDS_REVISION for any caption that invents.*?in the brief\.",
)
ok = patch(
    ROOT / "agents" / "copywriter" / "agent.py",
    "CONTEXT (required)",
    COPY_BLOCK,
    MARK_CW,
) and ok
sys.exit(0 if ok else 1)
