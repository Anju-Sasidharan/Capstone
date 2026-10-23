# Written by Anju for the Multi-Agent Creative Studio capstone (new file, not part
# of the original starter).
import os
import vertexai
from dotenv import load_dotenv

load_dotenv()
PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT")
LOCATION = os.getenv("CLOUD_RUN_REGION", "us-central1")
#Keep gets the current engine details from .env or enter the engine ID you want to keep. It will not be deleted.
KEEP = os.getenv("AGENT_ENGINE_RESOURCE_NAME", "").split("/")[-1]
# Enter the IDs of any engines you want to delete in OLD (inside ""). 
OLD = [""]
print("Keeping:", KEEP)

client = vertexai.Client(project=PROJECT, location=LOCATION)

print("Existing Agent Engines:")
for e in client.agent_engines.list():
    print(" ", e.api_resource.name)

for engine_id in OLD:
    if engine_id == KEEP:
        continue
    name = f"projects/{PROJECT}/locations/{LOCATION}/reasoningEngines/{engine_id}"
    try:
        client.agent_engines.delete(name=name, force=True)
        print("Deleted", engine_id)
    except Exception as exc:
        print("Skipped", engine_id, "-", type(exc).__name__, str(exc)[:150])