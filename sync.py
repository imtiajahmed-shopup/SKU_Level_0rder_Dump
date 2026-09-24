import os
import hashlib
import requests
from supabase import create_client

MB_URL = os.environ["METABASE_URL"].rstrip("/")
MB_SESSION_TOKEN = os.environ["METABASE_SESSION_TOKEN"]
MB_CARD_ID = os.environ["METABASE_CARD_ID"]

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

FROM_DATE = os.environ["FROM_DATE"]
TO_DATE = os.environ["TO_DATE"]

TABLE_NAME = os.environ.get("SUPABASE_TABLE", "sales_orders")

# Only these columns get kept and pushed to Supabase
WANTED_COLUMNS = [
    "sku", "product_name", "category", "order_type", "status",
    "order_qty", "lp", "sp", "order_value", "delivered_qty",
    "delivered_value", "return_qty", "return_value", "exchange_qty",
    "exchange_value", "damage_qty", "damage_value", "free_claimable_qty",
    "free_claimable_value", "free_non_claimable_qty", "free_non_claimable_value",
    "claimable_discount", "non_claimable_discount", "anchor_receivable",
    "db_id", "delivered_date", "sub_anchor_type", "sub_bu",
    "non_claimable_discount_total", "trade_discount",
    "claimable_discount_total", "nmv",
]


def fetch_card_data():
    headers = {
        "X-Metabase-Session": MB_SESSION_TOKEN,
        "Content-Type": "application/json",
    }

    payload = {
        "parameters": [
            {
                "type": "date/single",
                "target": ["variable", ["template-tag", "from"]],
                "value": FROM_DATE,
            },
            {
                "type": "date/single",
                "target": ["variable", ["template-tag", "to"]],
                "value": TO_DATE,
            },
        ]
    }

    url = f"{MB_URL}/api/card/{MB_CARD_ID}/query"

    print(f"Querying Metabase card {MB_CARD_ID}...")
    print(f"Date range: {FROM_DATE} to {TO_DATE}")

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
    except requests.RequestException as e:
        raise RuntimeError(f"Could not connect to Metabase: {e}") from e

    if resp.status_code == 401:
        raise RuntimeError(
            "Metabase session token is invalid or expired. "
            "Generate a new one and update the METABASE_SESSION_TOKEN secret."
        )

    if not resp.ok:
        print("========================================")
        print("METABASE API ERROR")
        print("========================================")
        print(f"Status code: {resp.status_code}")
        print(f"Response body: {resp.text}")
        print("========================================")
        raise RuntimeError(f"Metabase API returned HTTP {resp.status_code}")

    try:
        body = resp.json()
    except ValueError as e:
        raise RuntimeError(f"Metabase returned a non-JSON response: {resp.text}") from e

    if "data" not in body:
        raise RuntimeError(f"Unexpected Metabase response: {body}")

    data = body["data"]

    if "cols" not in data or "rows" not in data:
        raise RuntimeError(f"Metabase response is missing cols or rows: {data}")

    cols = [c["name"] for c in data["cols"]]
    rows = data["rows"]

    return [dict(zip(cols, row)) for row in rows]


def normalize_keys(records):
    return [{k.lower(): v for k, v in record.items()} for record in records]


def filter_columns(records):
    return [
        {col: record.get(col) for col in WANTED_COLUMNS}
        for record in records
    ]


def add_row_hash(records):
    for record in records:
        key = "|".join(
            str(record.get(field, ""))
            for field in ["sku", "delivered_date", "db_id", "order_type", "status"]
        )
        record["row_hash"] = hashlib.md5(key.encode("utf-8")).hexdigest()
    return records


def push_to_supabase(records):
    if not records:
        print("No records returned from Metabase. Nothing to sync.")
        return

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    batch_size = 500

    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]
        sb.table(TABLE_NAME).upsert(batch, on_conflict="row_hash").execute()
        print(f"Upserted batch {i // batch_size + 1} ({len(batch)} rows)")


def main():
    print(f"Syncing data from {FROM_DATE} to {TO_DATE}...")

    records = fetch_card_data()
    records = normalize_keys(records)

    print(f"Fetched {len(records)} rows from Metabase card {MB_CARD_ID}.")

    records = filter_columns(records)
    records = add_row_hash(records)
    push_to_supabase(records)

    print("Sync complete.")


if __name__ == "__main__":
    main()
