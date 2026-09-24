import os
import hashlib
import requests
from supabase import create_client

# ---- Config from environment ----
MB_URL = os.environ["METABASE_URL"].rstrip("/")
MB_SESSION_TOKEN = os.environ["METABASE_SESSION_TOKEN"]
MB_CARD_ID = os.environ["METABASE_CARD_ID"]

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

FROM_DATE = os.environ["FROM_DATE"]
TO_DATE = os.environ["TO_DATE"]

TABLE_NAME = os.environ.get("SUPABASE_TABLE", "sales_orders")


def fetch_card_data():
    headers = {"X-Metabase-Session": MB_SESSION_TOKEN}
    payload = {
        "parameters": [
            {
                "type": "date/range",
                "target": ["variable", ["template-tag", "date_range"]],
                "value": f"{FROM_DATE}~{TO_DATE}",
            }
        ]
    }
    resp = requests.post(
        f"{MB_URL}/api/card/{MB_CARD_ID}/query",
        headers=headers,
        json=payload,
        timeout=120,
    )
    if resp.status_code == 401:
        raise RuntimeError(
            "Metabase session token is invalid or expired. "
            "Generate a new one and update the METABASE_SESSION_TOKEN secret."
        )
    resp.raise_for_status()
    body = resp.json()
    data = body["data"]
    cols = [c["name"] for c in data["cols"]]
    rows = data["rows"]
    return [dict(zip(cols, row)) for row in rows]


def add_row_hash(records):
    for r in records:
        key = "|".join(
            str(r.get(field, ""))
            for field in ["sku", "delivered_date", "DB_id", "order_type", "status"]
        )
        r["row_hash"] = hashlib.md5(key.encode("utf-8")).hexdigest()
    return records


def push_to_supabase(records):
    if not records:
        print("No records returned from Metabase. Nothing to sync.")
        return
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    batch_size = 500
    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        sb.table(TABLE_NAME).upsert(batch, on_conflict="row_hash").execute()
        print(f"Upserted batch {i // batch_size + 1} ({len(batch)} rows)")


def main():
    print(f"Syncing data from {FROM_DATE} to {TO_DATE}...")

    records = fetch_card_data()
    print(f"Fetched {len(records)} rows from Metabase card {MB_CARD_ID}.")

    records = add_row_hash(records)
    push_to_supabase(records)

    print("Sync complete.")


if __name__ == "__main__":
    main()
