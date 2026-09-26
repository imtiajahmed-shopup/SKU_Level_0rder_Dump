import os
import json
import csv
import io
import requests
from datetime import date, timedelta
from supabase import create_client

MB_URL = os.environ["METABASE_URL"].rstrip("/")
MB_SESSION_TOKEN = os.environ["METABASE_SESSION_TOKEN"]
MB_CARD_ID = os.environ["METABASE_CARD_ID"]

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

TABLE_NAME = os.environ.get("SUPABASE_TABLE", "sales_orders")

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

sb = create_client(SUPABASE_URL, SUPABASE_KEY)


def get_last_synced_date():
    """Find the most recent delivered_date already in Supabase."""
    result = (
        sb.table(TABLE_NAME)
        .select("delivered_date")
        .order("delivered_date", desc=True)
        .limit(1)
        .execute()
    )
    if result.data:
        return result.data[0]["delivered_date"]
    return None


def compute_date_range():
    last_date_str = get_last_synced_date()
    yesterday = date.today() - timedelta(days=1)

    if last_date_str:
        last_date = date.fromisoformat(last_date_str)
        from_date = last_date + timedelta(days=1)
    else:
        # No data at all yet — fallback default (shouldn't happen since you backfilled manually)
        from_date = yesterday

    to_date = yesterday

    if from_date > to_date:
        return None, None  # already up to date, nothing new to fetch

    return from_date.isoformat(), to_date.isoformat()


def fetch_card_data(from_date, to_date):
    headers = {"X-Metabase-Session": MB_SESSION_TOKEN}

    payload = {
        "parameters": [
            {
                "type": "date/single",
                "target": ["variable", ["template-tag", "from"]],
                "value": from_date,
            },
            {
                "type": "date/single",
                "target": ["variable", ["template-tag", "to"]],
                "value": to_date,
            },
        ]
    }

    url = f"{MB_URL}/api/card/{MB_CARD_ID}/query/csv"

    print(f"Querying Metabase card {MB_CARD_ID} for {from_date} to {to_date}...")

    try:
        resp = requests.post(
            url,
            headers=headers,
            data={"parameters": json.dumps(payload["parameters"])},
            timeout=300,
        )
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
        print(f"Response body: {resp.text[:2000]}")
        print("========================================")
        raise RuntimeError(f"Metabase API returned HTTP {resp.status_code}")

    csv_text = resp.content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(csv_text))
    return list(reader)


def normalize_keys(records):
    return [{k.lower(): v for k, v in record.items()} for record in records]


def filter_columns(records):
    return [{col: record.get(col) for col in WANTED_COLUMNS} for record in records]


def clean_numeric_and_dates(records):
    numeric_cols = [c for c in WANTED_COLUMNS if c not in (
        "sku", "product_name", "category", "order_type", "status",
        "db_id", "delivered_date", "sub_anchor_type", "sub_bu"
    )]
    for r in records:
        for col in numeric_cols:
            val = r.get(col)
            if val is not None:
                val = str(val).replace(",", "").strip()
                r[col] = float(val) if val not in ("", "None") else None
    return records


def push_to_supabase(records):
    if not records:
        print("No new records to sync.")
        return

    batch_size = 500
    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]
        sb.table(TABLE_NAME).insert(batch).execute()
        print(f"Inserted batch {i // batch_size + 1} ({len(batch)} rows)")


def main():
    from_date, to_date = compute_date_range()

    if from_date is None:
        print("Supabase is already up to date. Nothing to sync.")
        return

    print(f"Syncing data from {from_date} to {to_date}...")

    records = fetch_card_data(from_date, to_date)
    records = normalize_keys(records)

    print(f"Fetched {len(records)} rows from Metabase card {MB_CARD_ID}.")

    records = filter_columns(records)
    records = clean_numeric_and_dates(records)
    push_to_supabase(records)

    print("Sync complete.")


if __name__ == "__main__":
    main()
