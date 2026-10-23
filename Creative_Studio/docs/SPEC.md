# Multi-Agent Creative Studio — Technical Specification

Source: `Multi-Agent Creative Studio _ Problem Statement, Requirements & Evaluation Guide.docx`
Status: v4 — reconciled with the implementation (Oct 21). Sections 1-15 are the design as planned; **§16 records where the built system differs, what was verified, and the guardrails added. Where they conflict, §16 wins.**

Tags used in this document:
- **[ASSUMPTION]** — a concrete default where the source doc is silent; override if the SDK or rubric disagrees.
- **[v2]** — new or materially changed since v1.

---

## 0. Changes in v2 (summary)

1. Critic verdict now has all three source sections (`posts_review`, `visuals_review`, `overall_assessment`) and a parse-failure policy (§7).
2. Explicit, documented approval threshold so the revision loop is deterministic and demoable (§7, §8).
3. Revision-cap behavior no longer conflicts with the "no PM before APPROVED" gate (§4.1, §8).
4. Inputs defined for Designer, Critic, and Project Manager (§4).
5. `caption_index`, `run_id`, and browsable image URLs added to the contracts; final `Campaign` gains a `tasks` list (§6).
6. IAM / auth, Secret Manager wiring, and Docker build-context rules added (§3, §10, §11).
7. Orchestrator free-text brief extraction, generation limits, env-configurable behavior, general error-recovery callbacks (§4, §8, §9).
8. README contents, demo recording, `.gitignore`, and the starter-repo/TODO requirement added (§3, §13).
9. Negative tests added to the verification plan (§12).
10. **[v2.1]** When the revision cap is hit, the user can choose to proceed with the current version or grant one more round of revisions (§4.1, §6.6, §6.7, §8).
12. **[v4]** Reconciled with the implementation: new §16 (deviations, guardrails, verification status, resolved assumptions) and short **[as-built v4]** notes at the top of the affected sections.
11. **[v3]** Shared context store: each agent writes its full output to its own file, other agents read it, and the orchestrator receives only a short summary plus a pointer (§5A, §6.8-6.9, and the per-agent "Context I/O" bullets in §4).

---

## 1. Purpose of This Document

The requirements doc defines *what* the system must do and how it will be graded. This spec defines *how* the pieces fit together precisely enough to implement without re-deriving decisions mid-build: message shapes between agents, the Critic's machine-readable format, retry/timeout numbers, env var contract, IAM, and repo layout.

Where the source doc leaves a detail open, this spec proposes a default (**[ASSUMPTION]**).

---

## 2. System Overview

A single orchestrator (**Creative Director**, on Vertex AI Agent Engine) drives five independent specialist agents (on Cloud Run), each reachable only over the A2A protocol. The orchestrator contains no specialist logic — it calls each specialist as a remote tool, carries structured context forward, and enforces a quality gate before producing a final campaign.

```
User
  │  free-text campaign brief
  ▼
Creative Director (Agent Engine)
  │
  ├─1─▶ Brand Strategist (Cloud Run)         research only
  ├─2─▶ Copywriter (Cloud Run)                3 caption variants, uses Skill
  ├─3─▶ Designer (Cloud Run)                  Gemini image model → GCS
  ├─4─▶ Critic (Cloud Run)                    APPROVED | NEEDS_REVISION
  │      └─ NEEDS_REVISION: re-run Copywriter (step 2) and/or Designer (step 3),
  │         then re-run Critic (step 4), until APPROVED or max cycles
  └─5─▶ Project Manager (Cloud Run)           timeline + tasks + optional Notion (MCP)
  │
  ▼
Final Campaign (research + captions + images + review + timeline + tasks)
```

Specialists never call each other; all routing goes through the Creative Director.

**[v3]** Control plane vs data plane: A2A carries short requests and short results between the orchestrator and specialists. Full outputs live in the shared context store (§5A), which specialists write to (their own file only) and read from (others' files), so the orchestrator's context does not grow with every output and revision cycle.

Shared infrastructure: Cloud Storage (images), Secret Manager (Notion token/DB ID), A2A (transport), MCP (Notion adapter).

---

## 3. Repository Layout & Build Rules

> **[as-built v4]** The real layout differs: no `/shared`, no `agent_card.json` files, Python deploy scripts instead of `.sh`. See §16.1 rows 1 and 15.

```
/agents
  /brand_strategist/     agent.py, tools.py, Dockerfile, agent_card.json
  /copywriter/           agent.py, tools.py, Dockerfile, agent_card.json
    /skills/instagram-copywriting/   caption_formulas.md, platform_rules.md, brand_voice_examples.md
  /designer/             agent.py, tools.py, Dockerfile, agent_card.json
  /critic/               agent.py, tools.py, Dockerfile, agent_card.json
  /project_manager/      agent.py, tools.py, Dockerfile, agent_card.json
  /creative_director/    agent.py, tools.py                (Agent Engine, no Dockerfile)
/deploy
  deploy_specialists.sh   # builds + pushes each Cloud Run service, writes URLs to config
  deploy_orchestrator.sh  # deploys Creative Director to Agent Engine
  teardown.sh
/shared
  schemas.py              # pydantic models shared by all agents (§6)
  retry.py                # retry/backoff decorator (§8)
  config.py               # reads env vars once, with defaults (§9)
.env.example
.gitignore                # must ignore .env, *.json key files, __pycache__, .venv
pyproject.toml            # managed with uv; python-dotenv for local .env loading
README.md
```

**[v2] Docker build context.** `/shared` sits outside each agent folder, so a Dockerfile in `agents/<name>/` cannot `COPY ../shared`. Rule: build every specialist with the **repo root as the build context** and an explicit Dockerfile path, e.g. `docker build -f agents/critic/Dockerfile .` (or `gcloud builds submit --config ...`), and have each Dockerfile `COPY shared/ ./shared/` plus its own agent folder. Python 3.12 base image.

**[v2] Starter code.** The requirements doc points to a starter repo with numbered `# TODO` comments in each agent file. If you build from it, every TODO must be completed, and this layout must be reconciled with the starter's folder structure (the submission requires `agents/` and `deploy/` at the repo root).

**[v2] Local tooling.** Python 3.11 or 3.12 locally (3.12 in containers); dependencies via `uv`; `python-dotenv` for `.env` loading.

**[v3] Context helper.** Each agent folder gets its own identical copy of a small `context_store.py` (`save_context`, `read_context`), with only the `AGENT_NAME` constant differing. This follows how the starter handles `retry.py` (one copy per agent) and respects that each Docker image is built from its own agent folder.

---

## 4. Agent Specifications

For each agent: role boundary, inputs, outputs, tools, and failure modes called out by the source doc.

### 4.1 Creative Director (Orchestrator)

> **[as-built v4]** The orchestrator is prompt-driven (`prompt.py`): no `CampaignState` object, no `return_partial` mode, up to 3 extra rounds at the cap, and a text final report instead of a `Campaign` JSON. See §16.1 rows 6, 7 and 13.

| | |
|---|---|
| Runtime | Vertex AI Agent Engine |
| Talks to user | Yes — only agent the user interacts with |
| Talks to specialists | Yes — as remote A2A tools, never inline logic |

Responsibilities:
- **[v2] Brief extraction.** The user supplies one free-text sentence or paragraph. The orchestrator extracts `product` and `target_audience` itself (filling a sensible default if missing) and **never asks the user a follow-up question** — the source scenario is a one-prompt run. It generates a `run_id` (§6.1).
- Read each specialist's Cloud Run URL from env vars; register each as a remote A2A tool via its agent card.
- Fixed call order: Brand Strategist → Copywriter → Designer → Critic → (loop) → Project Manager.
- Maintain a `CampaignState` (§6.6) threaded through every call — never re-derive prior output from raw text.
- **[v3] Context I/O.** Call a local `start_run()` tool to get the `run_id` (do not ask the LLM to invent one). For every specialist call, send the `run_id`, the `revision`, a `read_from` map of the context-file URIs that specialist should read, and on revisions the `top_fix` feedback. Keep only each `AgentResult` (summary + `context_uri`, §6.8) in state; never copy full outputs into the conversation. The orchestrator has a read-only `read_context` tool and uses it at the end to assemble the final `Campaign`. It writes no context files.
- **Gate:** must not call Project Manager until the (recomputed, §7) verdict is `APPROVED`. **[v2.1]** The only exception is an explicit user override at the revision cap (see "Cap reached" below).
- On `NEEDS_REVISION`: re-invoke Copywriter and/or Designer per `overall_assessment.revision_target`, passing `top_fix` (and the affected indices) as feedback, then re-invoke Critic. Repeat until approved or `MAX_REVISION_CYCLES` reached.
- **[v2.1] Cap reached.** When `revision_cycles` reaches `MAX_REVISION_CYCLES` and the verdict is still `NEEDS_REVISION`, behavior depends on `ON_CAP_BEHAVIOR` (§9):
  - `ask_user` (default for interactive use): the orchestrator ends its turn with a decision message instead of a final campaign. The message shows the current captions with image links (`https_url`), the Critic's scores, and the unresolved `top_fix`, and offers exactly two choices: **(1) try another round** of up to `MAX_REVISION_CYCLES` more cycles, or **(2) proceed with the current version**. It sets `awaiting_user_decision = true` in `CampaignState` (kept in the session, so the user's reply resumes the same run rather than starting over).
    - Choice 1: allowed only if `rounds_granted < MAX_EXTRA_ROUNDS` (default 1). Increment `rounds_granted`, reset the per-round cycle counter, and resume the loop. If the extra rounds are used up, offer only choice 2 (or stop with the partial campaign).
    - Choice 2: call the Project Manager with the current version. The Critic's `status` stays `NEEDS_REVISION` (the Critic format is never altered); the final `Campaign` sets `human_override = true` and a `note` stating the user accepted an unapproved version.
    - Any reply that is not clearly one of the two choices: re-ask; never infer approval.
  - `return_partial` (use for demos and automated tests): do **not** call the Project Manager. Return a partial `Campaign` with `review.overall_assessment.status = "NEEDS_REVISION"`, `timeline = null`, `tasks = []`, `notion_synced = false`, and a `note` explaining the cap was hit.
  - The user is asked only at the cap, never after each failed cycle. The gate is never bypassed silently.
- Assemble the final `Campaign` (§6.7) and return it to the user in a readable form (research, captions with their images, review, timeline, tasks).

### 4.2 Brand Strategist (Research)

| | |
|---|---|
| Runtime | Cloud Run |
| Input | `CampaignBrief` |
| Tools | web search |
| Forbidden | writing captions or visual descriptions (enforced in system instruction) |

- Every search query includes the current year (computed at call time, never hardcoded).
- Analyze 2–3 competitor brands; identify 3–5 trending topics.
- Output: four labelled sections — `audience_insights`, `competitive_analysis`, `trending_topics`, `key_strategic_insights`.
- **[v2]** Search failures are handled by an error-recovery callback (§8): return a clearly labelled "limited research" result rather than crashing.
- **[v3] Context I/O.** Reads nothing. Writes `strategist/rev0` containing the full `StrategistOutput`, and returns an `AgentResult` whose summary names the top insights and trending-topic titles.

### 4.3 Copywriter (Skill-backed)

| | |
|---|---|
| Runtime | Cloud Run |
| Input | `CampaignBrief` + `StrategistOutput` (structured JSON, §5) |
| Skill | `instagram-copywriting` (loaded on demand, not inlined into the base prompt) |

- Produce exactly 3 captions in distinct tonal registers — **[ASSUMPTION]** default: `inspirational`, `educational`, `community-focused`.
- Each caption: hook in line 1, 5–10 hashtags, exactly 1 CTA (**[v2]** enforced by schema validators, §6.3).
- On a revision cycle, receives the prior captions, `top_fix`, and `caption_indices` to change; incorporates the fix rather than regenerating everything.
- **[v3] Context I/O.** Overrides the Input row above: reads the Strategist's context file (URI from `read_from`) instead of receiving the full text. Writes `copywriter/rev{n}` containing the full `CopywriterOutput`; returns a summary (tones used, key hooks). On a revision it also reads its previous file and writes the next revision.

### 4.4 Designer (Multimodal)

> **[as-built v4]** Image paths are `campaign-images/<concept>-<id>.png`; signed links are produced by the Creative Director's `get_image_links` tool (TTL 1 hour). See §16.1 row 8.

| | |
|---|---|
| Runtime | Cloud Run |
| Input | **[v2]** `CampaignBrief` + `StrategistOutput` (key insights) + `CopywriterOutput` (captions) — so visuals match the copy and the research |
| Model | Gemini image model — called directly inside the tool function, **not** wired as an agent (no tool-calling support) |
| Storage | Cloud Storage bucket (from env var) |

- Tool signature: `generate_image(concept: str, image_prompt: str, aspect_ratio: Literal["1:1", "4:5"])`.
- Aspect ratio is not an API parameter — fold it into the text prompt sent to the image model. **[ASSUMPTION]** default `4:5` for feed posts unless the brief says otherwise.
- Uploads to `gs://$GCS_BUCKET_NAME/{run_id}/{caption_index}_{revision}.png` and returns `gcs_uri`, never raw bytes. Revisions get a new object (`revision` suffix) rather than overwriting, so the Critic never reads a stale or half-written file.
- **[v2]** Also returns a time-limited signed `https_url` for human viewing (the `gs://` URI is not browsable). **[ASSUMPTION]** signed URL TTL 7 days.
- At least one image per caption (≥3 images per campaign by default), each tagged with `caption_index`.
- **[v2]** Image-model refusals/safety blocks go through the error-recovery callback: rewrite the prompt more conservatively and retry once; otherwise report the failure for that caption.
- **[v3] Context I/O.** Overrides the Input row above: reads the Strategist and Copywriter context files. Writes `designer/rev{n}` containing the full `DesignerOutput` (all `ImageAsset`s with `gcs_uri`); returns a summary (image count, concepts). The images themselves stay in the bucket.

### 4.5 Critic (Quality Gate)

The orchestrator parses this agent's output programmatically — see §7 for the exact schema.

| | |
|---|---|
| Runtime | Cloud Run |
| Input | **[v2]** `CampaignBrief` + captions + `ImageAsset`s (with `gcs_uri`) |
| Tools | image-review tool |

- Scores captions and visuals 1–10.
- **[v2]** Calls the image-review tool **once per generated image**, which must actually load the stored image from GCS (multimodal call) — never infer quality from the prompt text.
- Three sections, all required: `posts_review`, `visuals_review`, `overall_assessment`.
- `overall_assessment.status`: `APPROVED` or `NEEDS_REVISION` — exact string.
- On `NEEDS_REVISION`: exactly one `top_fix` string, plus the indices that failed.
- **[v3] Context I/O.** Reads the Copywriter and Designer context files (latest revisions, given by the orchestrator) and the Strategist file for brand fit. Writes `critic/rev{n}` with the full verdict and detailed notes. **Exception to the summary rule:** the verdict JSON (§7) is also returned inline in `AgentResult.verdict`, because the orchestrator's gate and revision loop need it in context.

### 4.6 Project Manager (Planning + MCP)

> **[as-built v4]** Notion MCP was skipped; the Project Manager has no tools beyond the context store and returns a text timeline. See §16.1 rows 9 and 10.

| | |
|---|---|
| Runtime | Cloud Run |
| Input | **[v2]** The approved `CopywriterOutput`, `DesignerOutput` (with URIs), and brief |
| External tool | Notion via MCP (optional) |

- Always returns a full text timeline **and** a structured task list, regardless of Notion availability.
- **[v2]** Task fields: `title`, `owner_role`, `start`, `due`, `depends_on`, `status`. **[ASSUMPTION]** Notion database properties: Name (title), Status (select), Due (date), Owner (select/text), Campaign (text, = `run_id`). Document any property the target database must have.
- Notion sync is wrapped in an error-recovery callback: failed MCP calls are rewritten into an actionable hint; never a crash.
- Notion is enabled only when **both** `NOTION_API_TOKEN` and `NOTION_DATABASE_ID` are present (on Cloud Run these arrive as Secret Manager–backed env vars). Absence silently skips sync. A partial failure sets `notion_synced = false` and records which tasks failed in `notion_errors`.
- **[v3] Context I/O.** Reads the Copywriter, Designer, and Critic context files. Writes `project_manager/rev0` with the timeline and task list; returns a summary (start/end dates, task count, Notion status). Optional: if reading fails it may work from the summaries the orchestrator passes in.

---

## 5. A2A & MCP Wiring

> **[as-built v4]** Messages are text with `RUN_ID` / `REVISION` / `read_from` header lines, not JSON objects. See §16.1 row 2 and §16.4.

- Each specialist publishes an agent card at the A2A well-known path (**[ASSUMPTION]** `/.well-known/agent.json` — confirm against the ADK's A2A server default; ADK may generate the card for you).
- **[v2]** The card's advertised `url` must be the **deployed Cloud Run URL**, not `localhost`. Set it from an env var at container start (the deploy script knows the URL only after the first deploy — redeploy or set post-deploy if needed).
- Creative Director wraps each specialist by pointing at its agent card URL — no shared import of specialist code (shared *schemas* in `/shared` are fine).
- **[v2] Structured payloads over A2A.** **[ASSUMPTION]** Each message carries one JSON object (matching a §6 schema) as its payload, either as a data part or as a single JSON text part. Receivers validate with the shared pydantic model; on validation failure they return a short error naming the field instead of guessing.
- **[v2] Auth.** See §10 (IAM): Agent Engine's service account must be able to invoke each Cloud Run service.
- Verify reachability post-deploy with the A2A Inspector against each card.
- Project Manager connects to the Notion MCP server as a toolset — no custom Notion client code.

---

## 5A. Shared Context Store [v3]

**Purpose.** Stop the orchestrator's context from growing with every specialist output and every revision cycle. Each agent writes its full output to its own file; other agents read what they need; the orchestrator receives only a short summary and a pointer.

**Why this does not make agents less independent.** Specialists still never call each other and still run as separate A2A services. The shared files are a data side-channel: agents are coupled only by the file schema (§6.9) and the path convention below. This also complements the starter's `EventsCompactionConfig` (orchestrator TODO 3), which trims history; this section avoids putting bulk data in the history at all.

**Storage.** The existing images bucket (the starter's `GCS_IMAGES_BUCKET`; this spec's older `GCS_BUCKET_NAME` means the same bucket), at:

```
gs://<bucket>/context/{run_id}/{agent}/rev{n}.json
```

`agent` is one of `strategist`, `copywriter`, `designer`, `critic`, `project_manager`. **[ASSUMPTION]** the `context/` prefix does not collide with the Designer's image paths.

**Ownership rules** (each agent's file is editable only by that agent, readable by others):

1. **Single writer.** `save_context(content, summary, run_id, revision)` takes no agent name or path. `AGENT_NAME` is a constant in that agent's own `context_store.py`, so the tool can only write under that agent's prefix.
2. **Write-once.** Files are written with the GCS precondition `if_generation_match=0`, so an existing file cannot be overwritten, even by its owner. A revision writes `rev{n+1}`; old revisions stay for audit and the demo trace.
3. **Read-only for everyone else.** `read_context(uri)` reads one file. It accepts only URIs of the form `gs://<bucket>/context/{run_id}/...` whose `run_id` matches the current run. There is no list, delete, or update operation.
4. **No deletes by agents.** Cleanup is done only by `teardown.sh` (delete the `context/` prefix).
5. **Limitation.** Rules 1-4 are enforced in code, not by IAM, because the starter deploys all specialists with the same service account. Hard enforcement would need one service account per agent and IAM conditions on the object-name prefix. This is a possible stretch goal and is not planned.

**Who reads what:**

| Agent | Reads | Writes |
|---|---|---|
| Brand Strategist | — | `strategist` |
| Copywriter | `strategist` (and its own previous revision) | `copywriter` |
| Designer | `strategist`, `copywriter` | `designer` |
| Critic | `copywriter`, `designer`, `strategist` | `critic` |
| Project Manager | `copywriter`, `designer`, `critic` | `project_manager` |
| Creative Director | all (read-only, for final assembly) | none (holds `run_id`, URIs, summaries in `CampaignState`) |

**Per-step flow.**

1. The orchestrator calls `start_run()` and gets the `run_id`.
2. It calls a specialist with: the brief or a short instruction, `run_id`, `revision`, `read_from` (a map of agent name to context URI), and on revisions `feedback` (`top_fix`).
3. The specialist reads the listed files with `read_context`, does its work, calls `save_context` exactly once, and replies with an `AgentResult` (§6.8) only.
4. The orchestrator stores `context_uri` and `summary` in `CampaignState` and moves on. It never held the full output.
5. On a revision, the orchestrator updates `read_from` to the latest revision URIs before the next call. At the end it reads the files it needs to assemble the `Campaign`.

**Summary rules.** At most `CONTEXT_SUMMARY_MAX_WORDS` words (default 150), plain text, stating what the next step needs to know (key decisions, counts, constraints), not a copy of the content. No secrets and no credentials in any context file.

**Saving mechanism.** **[ASSUMPTION]** a `save_context` tool that the agent's instruction requires it to call once before replying (simplest, and matches the starter's tool pattern). If agents skip the call in testing, switch to a deterministic callback that saves the final output; verify the ADK's behavior for callbacks that replace the response before relying on this.

**Failure handling:** see §8 (context-store failures).

**Costs and risks (documented trade-offs).** A few extra GCS calls per agent (small latency); the LLM must reliably call the save/read tools; one more IAM grant for the orchestrator (§10); about 8-11 extra hours of work (see the plan spreadsheet).

---

## 6. Data Contracts

> **[as-built v4]** These contracts are conventions in the agent instructions, not pydantic models in `/shared`. `AgentResult` and `CampaignState` do not exist as objects. See §16.1 row 2.

Shapes each agent produces/consumes (not necessarily the literal A2A wire format). Implemented once as pydantic models in `/shared/schemas.py`.

### 6.1 `CampaignBrief` (user → Creative Director, after extraction)
```json
{ "run_id": "string (uuid)", "brief": "string", "product": "string", "target_audience": "string" }
```

### 6.2 `StrategistOutput`
```json
{
  "audience_insights": "string",
  "competitive_analysis": "string",
  "competitors": ["string", "2-3 items"],
  "trending_topics": ["string", "3-5 items"],
  "key_strategic_insights": "string",
  "search_year": 2026
}
```

### 6.3 `CaptionVariant`
```json
{ "index": 1, "tone": "inspirational|educational|community-focused|string", "hook": "string", "body": "string", "hashtags": ["5-10 items"], "cta": "string" }
```
`CopywriterOutput = { "captions": [CaptionVariant x3] }`

Validators: exactly 3 captions; distinct `tone`s; 5–10 hashtags; non-empty `hook` and `cta`.

### 6.4 `ImageAsset`
```json
{
  "caption_index": 1,
  "concept": "string",
  "image_prompt": "string",
  "aspect_ratio": "1:1|4:5",
  "revision": 0,
  "gcs_uri": "gs://bucket/run_id/1_0.png",
  "https_url": "string (signed, for humans)"
}
```
`DesignerOutput = { "images": [ImageAsset, ...] }` — at least one image per `caption_index`.

### 6.5 `CriticVerdict` — see §7.

### 6.6 `CampaignState` (threaded through the orchestrator)
```json
{
  "brief": "CampaignBrief",
  "strategist": "StrategistOutput | null",
  "copy": "CopywriterOutput | null",
  "designs": "DesignerOutput | null",
  "critic": "CriticVerdict | null",
  "revision_cycles": 0,
  "rounds_granted": 0,
  "awaiting_user_decision": false,
  "context_uris": { "strategist": "gs://...", "copywriter": "gs://...", "designer": "gs://...", "critic": "gs://...", "project_manager": "gs://..." },
  "summaries": { "strategist": "string", "copywriter": "string", "designer": "string", "critic": "string", "project_manager": "string" }
}
```
`revision_cycles` counts cycles in the current round and resets when the user grants another round. `rounds_granted` counts extra rounds granted so far.

**[v3]** During a run, `strategist`, `copy`, `designs`, and `critic` hold the **summary and `context_uri`** from each `AgentResult`, not the full objects. Full objects are loaded from the context store only when assembling the final `Campaign` (§5A). `context_uris` always point to the latest revision.

### 6.7 `Campaign` (final output to user)
```json
{
  "run_id": "string",
  "research": "StrategistOutput",
  "captions": ["CaptionVariant"],
  "images": ["ImageAsset"],
  "review": "CriticVerdict",
  "timeline": "string | null",
  "tasks": [
    { "title": "string", "owner_role": "string", "start": "YYYY-MM-DD", "due": "YYYY-MM-DD", "depends_on": ["string"], "status": "todo" }
  ],
  "notion_synced": false,
  "notion_errors": ["string"],
  "human_override": false,
  "note": "string | null"
}
```
`timeline` and `tasks` are only empty when the revision cap was hit and the run ended in `return_partial` mode (§4.1, §8). `human_override` is `true` only when the user chose to proceed with a version the Critic had not approved; in that case `review.overall_assessment.status` is still `NEEDS_REVISION`.

---

### 6.8 `AgentResult` (what every specialist returns to the orchestrator) [v3]
```json
{
  "status": "ok | degraded | error",
  "run_id": "string",
  "agent": "strategist | copywriter | designer | critic | project_manager",
  "revision": 0,
  "context_uri": "gs://<bucket>/context/<run_id>/<agent>/rev0.json | null",
  "summary": "string (at most CONTEXT_SUMMARY_MAX_WORDS words)",
  "verdict": "CriticVerdict | null",
  "inline_content": "object | null",
  "error": "string | null"
}
```
- `verdict` is set only by the Critic (§7).
- `status = "degraded"` means the context file could not be saved; `inline_content` then carries the full output so the run is not blocked (§8).
- `status = "ok"` requires a non-null `context_uri`; the orchestrator re-asks once if it is missing.

### 6.9 `ContextFile` (the JSON stored at each context URI) [v3]
```json
{
  "agent": "string",
  "run_id": "string",
  "revision": 0,
  "created_at": "ISO-8601 UTC timestamp",
  "read_from": ["gs://... (context files this agent used)"],
  "content": "the agent's full output object exactly as defined in §6.2-6.5 / §7 / §6.7 (timeline and tasks for the Project Manager)",
  "summary": "string (same text returned in AgentResult.summary)"
}
```

---

## 7. Critic Verdict — Exact Format

> **[as-built v4]** The Critic returns labelled text sections, not JSON, and applies the threshold itself; the orchestrator does not recompute it. See §16.1 row 5.

Drift here breaks the pipeline (the #1 common mistake in the source doc), so treat this as a strict schema. **[v2]** The three source sections map to the three top-level keys.

```json
{
  "posts_review": {
    "scores": { "caption_1": 8, "caption_2": 6, "caption_3": 9 },
    "notes": "string"
  },
  "visuals_review": {
    "scores": { "image_1": 7, "image_2": 5, "image_3": 8 },
    "notes": "string"
  },
  "overall_assessment": {
    "status": "NEEDS_REVISION",
    "summary": "string",
    "revision_target": ["copy", "visuals"],
    "failed_caption_indices": [2],
    "top_fix": "string | null"
  }
}
```

Rules:
- `status` ∈ `{"APPROVED", "NEEDS_REVISION"}` — literal match, no synonyms or casing variants.
- `revision_target` is empty iff `APPROVED`; otherwise a subset of `copy`, `visuals`.
- `failed_caption_indices` lists which caption/image pairs need rework (empty when approved).
- `top_fix` is non-null iff `NEEDS_REVISION`; it is exactly one fix.
- Score keys follow `caption_{index}` / `image_{caption_index}` so scores map back to `ImageAsset.caption_index`. One score per image.

**[v2] Approval threshold.** `APPROVAL_MIN_SCORE` (default **7**, env-configurable): the campaign is approvable only if **every** caption score and image score is ≥ the threshold. The Critic's prompt states this rubric. The orchestrator **recomputes** the verdict from the scores; if the Critic's `status` disagrees, the recomputed value wins and the discrepancy is logged. For a demo that is guaranteed to show the loop, raise the threshold (e.g. `APPROVAL_MIN_SCORE=9`) rather than faking a verdict.

**[v2] Parsing policy.** The Critic's tool use rules out relying on a structured-output schema in some ADK versions, so the Critic returns one JSON object as text. The orchestrator:
1. Strips code fences/prose, extracts the outermost JSON object, validates against the pydantic model.
2. On failure, re-invokes the Critic up to 2 times with a short format reminder (counts against the retry budget).
3. If it still fails, aborts the run with a clear error. It never defaults to `APPROVED` and never skips the gate.

**[v3] Where the verdict lives.** The verdict JSON above is returned inline in `AgentResult.verdict` (the orchestrator's gate needs it in context) and is also saved in the Critic's context file along with any longer notes.

---

## 8. Reliability & Revision-Loop Policy

> **[as-built v4]** Most of these values are not env-configurable. See §16.1 rows 4, 6 and 12.

All values are env-configurable (§9); the numbers below are defaults.

| Parameter | Default | Notes |
|---|---|---|
| Specialist retry attempts | 3 | exponential backoff with jitter |
| Orchestrator retry attempts | 5 | depends on every specialist succeeding |
| Backoff base / max | **[ASSUMPTION]** 1s / 30s | tune against observed Vertex AI quota errors |
| Retryable errors | 429, 500, 502, 503, 504, timeouts, connection resets | **never** retry 400/401/403/schema-validation errors |
| `MAX_REVISION_CYCLES` | **[ASSUMPTION]** 3 | cycles per round; on reaching it, follow `ON_CAP_BEHAVIOR` (§4.1) |
| `MAX_EXTRA_ROUNDS` | **[v2.1]** 1 | extra rounds the user may grant at the cap; bounds total cycles to `MAX_REVISION_CYCLES × (1 + MAX_EXTRA_ROUNDS)` = 6 |
| `ON_CAP_BEHAVIOR` | **[v2.1]** `ask_user` | `ask_user` = decision message to the user; `return_partial` = no PM call, partial campaign (demos/tests) |
| Per-specialist-call timeout | **[ASSUMPTION]** 120s | give up rather than hang |
| Overall run timeout | **[ASSUMPTION]** 15 min | bound the nested retries × timeouts |
| Generation limits (orchestrator) | **[v2]** `ORCH_MAX_OUTPUT_TOKENS` set; temperature low | source §5.8 asks for generation limits |
| `APPROVAL_MIN_SCORE` | 7 | see §7 |
| `CONTEXT_SUMMARY_MAX_WORDS` | **[v3]** 150 | cap on returned summaries (§5A) |

**[v2] Idempotency.** Retries must not duplicate side effects: Designer uses deterministic object names (`run_id` + `caption_index` + `revision`), so a retried call overwrites its own object only; Project Manager tags Notion tasks with `run_id` and skips tasks that already exist.

**[v3] Context-store failures.** A failed `save_context` goes through the normal retry policy (transient errors only). If saving still fails, the agent returns `status = "degraded"` with `inline_content` so the campaign continues, and the orchestrator logs it. A failed `read_context` is retried the same way; if it still fails, the agent works from the summary the orchestrator passed in and says so in its own summary. A write-once conflict (file already exists for that revision) on a retried call is treated as success for the same agent and revision, so retries do not duplicate or corrupt files.

**[v2] Error-recovery callbacks (general pattern).** Every specialist with an external tool wraps it: Project Manager (Notion MCP), Designer (image model/GCS), Strategist (search), Critic (image fetch). A failed tool call is caught and rewritten into an actionable hint the agent can act on; it never propagates as an unhandled crash. Notion failure never prevents the timeline from being returned.

---

## 9. Configuration (Environment Variables)

> **[as-built v4]** The real variable names are listed in §16.1 row 4 and in the README (section 6).

`.env.example` must define at minimum (placeholders only; real secrets come from Secret Manager):

```
# Model config
TEXT_MODEL=
IMAGE_MODEL=
VERTEX_REGION=global          # model endpoint only — never for Cloud Run
CLOUD_RUN_REGION=us-central1  # real region, required by Cloud Run

# GCP project
GCP_PROJECT_ID=
# ADK/Vertex SDK typically also expect GOOGLE_GENAI_USE_VERTEXAI, GOOGLE_CLOUD_PROJECT,
# GOOGLE_CLOUD_LOCATION — map them from the values above in config.py [ASSUMPTION: verify names]

# Storage
GCS_BUCKET_NAME=

# Specialist service addresses (filled in by deploy scripts)
BRAND_STRATEGIST_URL=
COPYWRITER_URL=
DESIGNER_URL=
CRITIC_URL=
PROJECT_MANAGER_URL=

# Behavior (all optional; defaults in §8)
MAX_REVISION_CYCLES=3
MAX_EXTRA_ROUNDS=1
ON_CAP_BEHAVIOR=ask_user       # ask_user | return_partial
APPROVAL_MIN_SCORE=7
SPECIALIST_RETRIES=3
ORCHESTRATOR_RETRIES=5
BACKOFF_BASE_SECONDS=1
BACKOFF_MAX_SECONDS=30
SPECIALIST_TIMEOUT_SECONDS=120
ORCH_MAX_OUTPUT_TOKENS=
CONTEXT_SUMMARY_MAX_WORDS=150

# Notion (optional — both required to enable sync; absence disables sync, not an error)
NOTION_API_TOKEN=
NOTION_DATABASE_ID=
```

On Cloud Run the two Notion values are injected from Secret Manager, not from a committed file.

---

## 10. Deployment, IAM & Secrets

> **[as-built v4]** One default compute service account, unauthenticated Cloud Run, Python deploy scripts. See §16.1 rows 11 and 15.

- One Dockerfile per specialist (Python 3.12), built with the repo root as context (§3).
- `deploy_specialists.sh`: builds + pushes each container to Artifact Registry, deploys to Cloud Run in `CLOUD_RUN_REGION`, captures each URL, writes it into the config consumed by the Creative Director. Mounts Notion secrets (`--set-secrets`) on the Project Manager only.
- `deploy_orchestrator.sh`: deploys Creative Director to Agent Engine with the specialist URLs and behavior env vars passed through at deploy time.
- `teardown.sh`: deletes the five Cloud Run services and the Agent Engine deployment; also removes Artifact Registry images. Documents (and optionally performs) bucket/secret deletion.
- Required GCP APIs: Vertex AI, Cloud Run, Cloud Storage, Secret Manager, Artifact Registry.

**[v2] IAM / auth (least privilege) — [ASSUMPTION] one service account per service:**

| Principal | Needs |
|---|---|
| Every specialist's service account | Vertex AI user (model calls) |
| Designer SA | Storage object creator/admin on the bucket; permission to sign URLs |
| Critic SA | Storage object viewer on the bucket |
| Project Manager SA | Secret Manager secret accessor (Notion secrets only) |
| Agent Engine service identity | Cloud Run invoker on each specialist (Cloud Run is **not** public; the orchestrator presents an identity token) |
| Specialists' service accounts | **[v3]** Storage object create and get on the bucket for the `context/` prefix (most already have this for image upload and review) |
| Agent Engine service identity | **[v3]** Storage object get on the bucket, so the orchestrator can read context files for final assembly |

**[v2] Secrets.** The Notion token and database ID live only in Secret Manager. They never appear in the repo, `.env.example`, logs, or deploy-script output. `.gitignore` excludes `.env` and any service-account key files; run a secret scan before pushing.

---

## 11. Observability (minimal)

> **[as-built v4]** See §16.1 row 14.

Each run logs, keyed by `run_id`: each specialist call (name, duration, attempt number), each Critic verdict (scores, status, recomputed status), each revision cycle (target, `top_fix`), and each recovered error. This makes the revision loop visible for the demo and debuggable after.

---

## 12. Verification Plan (maps to source doc §5.9)

> **[as-built v4]** The status of every check is in §16.3.

| Check | Method |
|---|---|
| Each specialist's output shape | Run locally in ADK dev UI; validate against §6 models |
| Strategist | Four sections present; 2–3 competitors; 3–5 trends; search queries contain the current year |
| Copywriter | Skill is actually loaded (check trace); 3 distinct tones; hashtag/CTA counts |
| Designer end-to-end | Image lands in GCS; returned `gcs_uri` matches; `https_url` opens |
| Critic format | Known-good and known-bad samples both produce schema-valid JSON; `APPROVED` and `NEEDS_REVISION` exact strings |
| Critic reviews real images | Per-image tool call appears in trace for every image |
| Revision loop | Trace one full run (use `APPROVAL_MIN_SCORE=9` if needed) where `NEEDS_REVISION` occurs ≥1 time; confirm the right specialist is re-called per `revision_target` and the Critic re-runs |
| **[v2]** Parse failure | Feed malformed Critic output; confirm reminder retries, then a clean abort — never an approval |
| **[v2]** Cap behavior (`return_partial`) | Force `MAX_REVISION_CYCLES=1` with a strict threshold and `ON_CAP_BEHAVIOR=return_partial`; confirm partial campaign and **no** PM call |
| **[v2.1]** Cap decision: proceed | `ON_CAP_BEHAVIOR=ask_user`; at the cap reply "proceed"; confirm PM runs, `human_override = true`, Critic status still `NEEDS_REVISION`, and a note is present |
| **[v2.1]** Cap decision: another round | Reply "another round"; confirm `rounds_granted = 1`, the cycle counter resets, and the loop resumes in the same run (same `run_id`) |
| **[v2.1]** Round limit | After the extra round is used, confirm "another round" is no longer offered and total cycles never exceed 6 |
| **[v2.1]** Ambiguous reply | Reply with something unclear; confirm the orchestrator re-asks and does not call PM |
| **[v2.1]** Session continuity | Confirm the decision reply resumes from stored `CampaignState` (no re-run of Strategist/Copywriter/Designer) |
| **[v2]** Notion failures | Run with token absent (silent skip), and with an invalid token (hint returned, timeline still returned) |
| **[v2]** Transient errors | Inject a 429/503; confirm backoff and eventual success |
| Network reachability | A2A Inspector on each deployed card; confirm card `url` is the Cloud Run URL |
| **[v2]** Security | Secret scan of repo; confirm `.env` is not tracked |
| **[v2]** Cheap automated tests (optional) | Unit tests for the Critic parser, schema validators, and threshold recomputation |
| **[v3]** Context write/read | Each agent writes exactly one file per run per revision at the expected path; content validates against its §6 schema; the next agent reads it successfully |
| **[v3]** Ownership | Attempt to overwrite an existing file, or to write outside an agent's own prefix, is rejected |
| **[v3]** Cross-run read | `read_context` with a URI from a different `run_id` is rejected |
| **[v3]** Summary size | Summaries stay within `CONTEXT_SUMMARY_MAX_WORDS`; in a 3-cycle run the orchestrator's context holds summaries and URIs, not full outputs (check the trace) |
| **[v3]** Degraded mode | Break writes for one agent (wrong bucket value); confirm `status = "degraded"`, inline content, and that the run still completes |
| **[v3]** Missing URI | Return `status = "ok"` with no `context_uri`; confirm the orchestrator re-asks once |
| **[v3]** Revisions | After a `NEEDS_REVISION`, a new `rev{n+1}` file appears and the Critic reads the latest revision, not the old one |

---

## 13. Deliverables Checklist

| Deliverable | Notes |
|---|---|
| All six agents | Every starter TODO completed (if using the starter) |
| Dockerfiles | One per specialist, builds from repo root |
| Deploy scripts | Specialists, orchestrator, teardown |
| `.env.example` | Placeholders only |
| `README.md` | **[v2]** Must cover: prerequisites (GCP project, billing, APIs, Python 3.11/3.12, uv), configuration, running a specialist locally in the ADK dev UI, deploying, running a campaign, verification steps, sample briefs (include the EcoFlow example), Notion setup (optional), teardown; **[v3]** how the shared context store works and its ownership rules |
| Demo | **[v2]** Recording or screenshots of one full campaign **including a revision-loop pass** |
| Not included | `.env`, API keys, service-account keys, plaintext Notion token/DB ID |

---

## 14. Traceability to Evaluation Criteria

| Spec section | Evaluation criterion | Weight |
|---|---|---|
| §4.1, §6.6 | Multi-Agent Orchestration | 20% |
| §5, agent cards | A2A & Distributed Design | 15% |
| §4.4, §6.4 | Multimodal Image Generation | 15% |
| §7, §8 (revision cycles) | Quality Gate & Revision Loop | 20% |
| §4.3 (Skill), §4.6 (MCP) | Skills & MCP Integration | 10% |
| §8 | Reliability & Error Handling | 10% |
| §3, §9, §10, §13 | Deployment & Code Quality | 10% |
| §5A, §6.8-6.9 (v3) | Supports Multi-Agent Orchestration and A2A & Distributed Design (not a separate criterion) | — |

---

## 15. Open Assumptions to Confirm

1. Agent card served at ADK's default A2A well-known path; card `url` set from env var.
2. Structured payload carried as a data part or single JSON text part.
3. Notion sync enabled only when both token and database ID are present; Notion DB property names.
4. Retry constants (1s/30s, jitter), retryable-error list.
5. `MAX_REVISION_CYCLES = 3` per round; `MAX_EXTRA_ROUNDS = 1`; run timeout 15 min; per-call timeout 120s.
5a. **[v2.1]** Agent Engine sessions keep `CampaignState` between turns, so the user's decision reply resumes the same run. Verify this against your ADK/Agent Engine version early; if state doesn't persist, fall back to `return_partial`. The run timeout applies per turn, not across the user's decision.
6. `APPROVAL_MIN_SCORE = 7`; orchestrator recomputes status from scores.
7. Signed-URL TTL of 7 days.
8. One service account per service with the IAM roles in §10.
9. ADK/Vertex env var names (`GOOGLE_*`) to verify against your ADK version.
10. Whether structured output schemas can be combined with tools in your ADK version (affects Critic parsing, §7).
11. **[v3]** Context files are JSON in the existing images bucket under `context/{run_id}/{agent}/rev{n}.json`, with no collision with image paths.
12. **[v3]** Ownership is enforced in code (fixed `AGENT_NAME`, write-once via GCS precondition), not by IAM, because the starter's specialists share a service account.
13. **[v3]** Agents save via a `save_context` tool they are instructed to call once. If they skip it in testing, switch to a callback.
14. **[v3]** Each agent folder carries its own copy of `context_store.py`.
15. **[v3]** Agent Engine's service identity can be granted read access to the bucket.

---

## 16. As-Built Reconciliation [v4]

Sections 1-15 describe the design. This section records what was actually built, what was verified, and what was added. Where the two conflict, this section is correct. The README (docs/README.md) has the commands and the troubleshooting log.

### 16.1 Where the implementation differs from the design

| # | Area | Spec said | As built | Why |
|---|---|---|---|---|
| 1 | Repository layout | `/shared` (schemas, retry, config), `agent_card.json`, `.sh` deploy scripts | No `/shared`: each agent folder has its own copy of `retry.py` and `context_store.py`. Agent cards are generated by the ADK A2A server. Deploy scripts are Python (`deploy_all_specialists.py`, `deploy_orchestrator.py`) plus `teardown_gcp.sh`. Added: `guardrails.py`, `run_tools.py`, `get_image_links_tool.py`, `chat_deployed.py`, `tests/` | Starter structure; each container builds from its own folder |
| 2 | Data contracts and messages | Pydantic models; JSON payloads; `AgentResult`, `CampaignState` | Conventions in the agent instructions. A request starts with `RUN_ID:`, `REVISION:` and `read_from:` lines. A specialist replies with a short summary and `Context saved: <uri>`. Context files follow §6.9 except `read_from` is saved empty. No schema validation | LLM agents with text input and output |
| 3 | Agent names in the store | `strategist` | `brand_strategist`, `copywriter`, `designer`, `critic`, `project_manager`. The Creative Director has a read-only copy of the helper | Matches the folder names |
| 4 | Environment variables | `TEXT_MODEL`, `IMAGE_MODEL`, `GCS_BUCKET_NAME`, `*_URL`, behavior variables | `GEMINI_MODEL`, `GEMINI_IMAGE_MODEL`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `CLOUD_RUN_REGION`, `GCS_IMAGES_BUCKET`, `STRATEGIST_AGENT_URL`, `COPYWRITER_AGENT_URL`, `DESIGNER_AGENT_URL`, `CRITIC_AGENT_URL`, `PM_AGENT_URL`, `SIGNING_SERVICE_ACCOUNT`, `APPROVAL_MIN_SCORE`, `CONTEXT_SUMMARY_MAX_WORDS`, `AGENT_ENGINE_RESOURCE_NAME`, `AGENT_ENGINE_ID`. The cycle, extra-round, `ON_CAP_BEHAVIOR`, retry and timeout settings are not environment variables | Starter names; fixed behavior kept in the prompt and `retry.py` |
| 5 | Critic verdict | JSON object; orchestrator recomputes status from scores | Text with POSTS REVIEW, VISUALS REVIEW and OVERALL ASSESSMENT (`All Approved`, `Priority Revisions`, `Revision Target`, `Failed Captions`, `Failed Images`, `Overall Score`). The Critic applies `APPROVAL_MIN_SCORE` (environment variable on the Critic service, default 7). The orchestrator reads the fields and does not recompute. A missing section: ask the Critic once to resend; a second failure is a hard failure; never treated as approved | Text works reliably with tool use; the rule is explicit in the prompt |
| 6 | Revision loop and cap | 3 cycles, 1 extra round, `ask_user` or `return_partial` | 3 automatic rounds, then the user chooses "another round" (up to 3 extra) or "proceed". `return_partial` is not implemented. "Proceed" runs the Project Manager and labels the report "Delivered without full Critic approval (human override)". `Revision Target` is matched case-insensitively. The Designer regenerates only `Failed Images`; the Copywriter revises only `Failed Captions` | Simpler for a prompt-driven orchestrator |
| 7 | Final output | `Campaign` JSON | Readable report: strategy summary, posts copied exactly from the Copywriter's file, image links, quality review, timeline, run details (all context URIs) | Human-readable demo output |
| 8 | Images and links | `{run_id}/{index}_{revision}.png`; Designer returns `https_url` (TTL 7 days); deterministic names | `campaign-images/<concept>-<random id>.png`. Signed V4 links are created by the Creative Director's `get_image_links` tool through IAM SignBlob; TTL 1 hour. Object names are not deterministic | Signing needs a service-account identity available to the orchestrator |
| 9 | Notion MCP | Optional integration | Skipped. The report says "Notion sync: not enabled". Skills are done; MCP is not | Time; the starter's no-Notion path keeps the agent working |
| 10 | Project plan | Structured `tasks` list | Text timeline and deliverables. No invented budget (the agent writes "Budget: to be confirmed") | The Project Manager had invented a budget and a sync |
| 11 | IAM and auth | One service account per service; Cloud Run not public; identity tokens | All specialists run as the default compute service account with `--allow-unauthenticated` (starter default). The Agent Engine service agent has object viewer on the bucket and token creator on the compute service account. No identity tokens. **Known limitation** | Time; documented in the README |
| 12 | Retry and timeouts | Specified numbers, 15-minute run timeout | Each agent's `retry.py` retries quota and transient errors; 120-second model timeout on the orchestrator; one prompt-level retry when a context save is missing. No overall run timeout | Starter retry configuration |
| 13 | Brief handling | Orchestrator extracts product and audience | Prompt-driven. The input guardrail (§16.2) refuses empty, oversized, injection and harmful briefs | |
| 14 | Observability | Per-call logging by `run_id` | ADK `LoggingPlugin`, Cloud Logging per service, Agent Engine tracing enabled, and the "Run details" block in every report | Enough for the demo |
| 15 | Deployment | Docker build from the repo root, `.sh` scripts | Cloud Run `--source` deploys from each agent folder (Dockerfile with `uv sync`), run sequentially by `deploy_all_specialists.py` (about 20 minutes; rebuilds all five); an Artifact Registry repository is created; URLs are written to `.env`. The orchestrator is created on Agent Engine by `deploy_orchestrator.py` (new resource per deploy, staging bucket `<project-id>-agent-staging`, environment variables passed explicitly, resource name written to `.env`) | Starter scripts, fixed for Windows |
| 16 | Idempotency | Deterministic object names | Context files are write-once (an identical retry counts as success); image objects have random suffixes | |

### 16.2 Guardrails (added after the original spec)

| Guardrail | Where | Behavior |
|---|---|---|
| Input screen | `agents/creative_director/guardrails.py`, `before_model_callback` | Before any model call: refuses an empty brief, a brief over 2,000 characters, prompt-injection phrases, and clearly harmful requests (fake reviews, counterfeit, deepfakes and similar). Ignores tool results and short replies such as "proceed". Sets the session state key `guardrail_blocked` |
| Output claim lint | same file, `after_model_callback` | Scans the final report for risky claims (clinical, cure, guarantee, detox, regulatory, unsourced statistics) and appends a visible "Compliance check" note. Warns only; never deletes |
| Quality gate | Critic, `prompt.py` | Score threshold, targeted revisions, 3 rounds, human decision |
| No fabrication | agent instructions | No invented `gs://` URIs, "Context saved" only after an ok result, no invented features or testimonials (Copywriter), no invented budget or sync (Project Manager), captions copied verbatim into the report |
| Data safety | `context_store.py` | Write-once, single-writer files; read-only for other agents |

Tests: `tests/test_guardrails.py` (input rules, claim lint, tool-result skipping, and an end-to-end run through a real ADK runner with a stub model). The injection refusal was also verified live in the dev UI and against the deployed Agent Engine orchestrator (no specialist was called).

Limits: the checks are simple rules. Off-topic briefs are not blocked, and the claim lint does not catch invented product features. In one run the approved captions claimed Apple Watch and Oura integration and humidity-adaptive goals that were not in the brief.

### 16.3 Verification status (maps to §12)

| Check | Status | Evidence |
|---|---|---|
| Specialist output shapes | Done | Dev UI runs; context files in the bucket |
| Strategist (four sections, year in queries) | Done | `groundingMetadata.webSearchQueries` in the dev UI |
| Copywriter (Skill loaded, tones, hashtags, CTA) | Done | Dev UI trace; captions in the context file |
| Designer end to end | Done | Images in the bucket; signed links opened in a browser |
| Critic format and exact strings | Done | Stable verdict text across cloud runs |
| Critic reviews real images | Done | One `review_image` call per image; caught real defects |
| Revision loop | Done | Cloud runs `run-20261017-182304-b478`, `run-20261018-020712-6be3`, `run-20261020-210156-a957`, `run-20261020-215735-5a94`, `run-20261021-005930-a3dc` (approved at 9/10 after one revision) |
| Parse failure (malformed Critic output) | Not tested | Rule is in the prompt |
| Cap with `return_partial` | Not applicable | Not implemented |
| Cap decision: proceed | Done | Runs 17 Oct, 18 Oct and `run-20261020-215735-5a94` (human-override label in the report) |
| Cap decision: another round | Done | Deployed orchestrator: the extra round ran in the same run (same `run_id`) |
| Round limit | Not tested | Optional (needs three extra rounds) |
| Ambiguous reply at the decision | Done | Defect found: "may be" started a round. Fixed with a re-ask rule in `prompt.py`. Verified in `run-20261022-145711-8ae3`: "may be" and a question were each answered and the two options repeated |
| State recovery after a long Q&A | Done | Defect found: after several decision-phase turns the agent lost the run ID and URIs. Fixed with the run ID in session state, the `get_run_state` tool and a prompt rule. Verified in `run-20261022-145711-8ae3` ("proceed" delivered the final report) |
| Session continuity | Done | On Agent Engine, the "proceed" reply resumed the same run without re-running earlier agents |
| Notion failures | Not applicable | Notion skipped |
| Transient errors | Partly | Quota errors (429) occurred during testing and were handled by retry and waiting; none were injected deliberately |
| Agent cards and reachability | Done | All five cards advertise their Cloud Run URLs (checked by script). The A2A Inspector was not run |
| Security: secret scan | Done | Oct 22: `git grep --cached` for signatures, private keys, API keys and the project number found nothing; `.env` is ignored; no `.env`, `.txt` or key files staged |
| Automated tests | Partly | Guardrail tests only |

### 16.4 Open assumptions from §15: how they resolved

1. Agent card path `/.well-known/agent.json`: confirmed (all five answer).
2. Payload carried as text with header lines, not JSON.
3. Notion skipped.
4. Retry constants: the starter's `retry.py` configuration.
5. Cycle limit 3; extra rounds up to 3 (not 1); no overall run timeout.
5a. Agent Engine sessions keep the run state between turns: confirmed (the decision reply resumed the same run).
6. The orchestrator does not recompute the verdict; the Critic decides with `APPROVAL_MIN_SCORE`.
7. Signed-link TTL is 1 hour (not 7 days).
8. One default service account for all specialists.
9. Variable names: see §16.1 row 4.
10. Structured output was not combined with tools; the Critic returns text.
