import os
import requests
import json

MB_URL = os.environ["METABASE_URL"].rstrip("/")
MB_SESSION_TOKEN = os.environ["METABASE_SESSION_TOKEN"]
MB_CARD_ID = os.environ["METABASE_CARD_ID"]

headers = {"X-Metabase-Session": MB_SESSION_TOKEN}

resp = requests.get(f"{MB_URL}/api/card/{MB_CARD_ID}", headers=headers, timeout=30)
resp.raise_for_status()
card = resp.json()

template_tags = card.get("dataset_query", {}).get("native", {}).get("template-tags", {})

print("=== TEMPLATE TAGS FOUND ON THIS CARD ===")
print(json.dumps(template_tags, indent=2))
print("=== END ===")
