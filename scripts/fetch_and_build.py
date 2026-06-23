#!/usr/bin/env python3
"""
Fetch US leads and deals from HubSpot API and rebuild both Sankey dashboards.

Requires HUBSPOT_API_KEY env var (private app access token).
"""

import os
import sys
import json
import urllib.request

HUBSPOT_API_KEY = os.environ.get("HUBSPOT_API_KEY")
if not HUBSPOT_API_KEY:
    print("ERROR: HUBSPOT_API_KEY env var not set")
    sys.exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.join(SCRIPT_DIR, "..")


# ── Generic HubSpot helpers ──────────────────────────────────────────────────

def hubspot_search(object_type, properties, filters=None, after=None):
    url = f"https://api.hubapi.com/crm/v3/objects/{object_type}/search"
    body = {
        "limit": 100,
        "properties": properties,
        "sorts": [{"propertyName": "createdate", "direction": "ASCENDING"}],
    }
    if filters:
        body["filterGroups"] = [{"filters": filters}]
    if after:
        body["after"] = after

    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={
            "Authorization": f"Bearer {HUBSPOT_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


# HubSpot's Search API refuses to paginate past 10,000 records (after + limit
# must stay <= 10,000). We page with the `after` cursor up to WINDOW_PAGES, then
# re-anchor a fresh search on `createdate >= last_seen` and keep going. Records
# are sorted by createdate ASC, and we dedup by id since the re-anchored window
# re-fetches records sharing the boundary timestamp.
WINDOW_PAGES = 90  # 9,000 records per window — safely under the 10k cap


def fetch_all(object_type, properties, filters=None):
    all_records = []
    seen_ids = set()
    last_createdate = None
    page = 0
    while True:
        window_filters = list(filters) if filters else []
        if last_createdate is not None:
            window_filters.append({
                "propertyName": "createdate",
                "operator": "GTE",
                "value": last_createdate,
            })

        after = None
        window_page = 0
        progressed = False
        while window_page < WINDOW_PAGES:
            page += 1
            window_page += 1
            print(f"  Page {page}...")
            result = hubspot_search(object_type, properties, window_filters or None, after)
            records = result.get("results", [])
            for r in records:
                rid = r.get("id")
                if rid not in seen_ids:
                    seen_ids.add(rid)
                    all_records.append(r)
                    progressed = True
                cd = r.get("properties", {}).get("createdate")
                if cd:
                    last_createdate = cd
            after = result.get("paging", {}).get("next", {}).get("after")
            if not after or not records:
                return all_records

        # Hit the window cap; re-anchor on last_createdate via the outer loop.
        # If a full window yielded nothing new, stop to avoid an infinite loop
        # (e.g. >9,000 records sharing one exact createdate).
        if not progressed:
            print("  WARNING: window made no progress; stopping pagination early")
            return all_records


def build_html(template_name, output_name, data_var, data):
    template_path = os.path.join(ROOT_DIR, template_name)
    output_path = os.path.join(ROOT_DIR, output_name)

    with open(template_path) as f:
        template = f.read()

    data_js = f"const {data_var} = " + json.dumps(data) + ";"
    html = template.replace("%%DATA_PLACEHOLDER%%", data_js)

    with open(output_path, "w") as f:
        f.write(html)

    print(f"  Written {output_name} ({len(data)} records, {os.path.getsize(output_path) // 1024} KB)")


# ── Leads ────────────────────────────────────────────────────────────────────

LEAD_PROPERTIES = [
    "createdate",
    "hs_lead_trigger",
    "hs_date_entered_new",
    "hs_date_entered_attempting",
    "hs_date_entered_connected",
    "hs_date_entered_pre_qualified",
    "hs_date_entered_qualified",
]

LEAD_PROP_MAP = {
    "created": "createdate",
    "trigger": "hs_lead_trigger",
    "new": "hs_date_entered_new",
    "attempting": "hs_date_entered_attempting",
    "connected": "hs_date_entered_connected",
    "prequalified": "hs_date_entered_pre_qualified",
    "qualified": "hs_date_entered_qualified",
}


def parse_lead(record):
    props = record.get("properties", {})
    def g(key):
        return props.get(LEAD_PROP_MAP[key]) or None
    return [
        g("created"), g("new"), g("attempting"), g("connected"),
        g("prequalified"), g("qualified"),
        props.get(LEAD_PROP_MAP["trigger"], ""),
    ]


def build_leads():
    print("Fetching leads...")
    raw = fetch_all("leads", LEAD_PROPERTIES)
    print(f"  Got {len(raw)} leads")
    data = [parse_lead(r) for r in raw]
    data = [d for d in data if d[0]]
    build_html("template-leads.html", "index.html", "LEADS_RAW", data)


# ── Deals ────────────────────────────────────────────────────────────────────

# Pipeline ID for "Sales - Global" — update if yours differs
SALES_GLOBAL_PIPELINE = "74974043"

DEAL_PROPERTIES = [
    "createdate",
    "pipeline",
    "dealstage",
    "hubspot_owner_id",
    "americas_deal_segment",
    # Date entered properties use the stage ID as suffix.
    # These are the IDs for Sales - Global stages.
    # If they don't return data, check your HubSpot for the correct property names.
    "hs_date_entered_qualifying",
    "hs_date_entered_validating",
    "hs_date_entered_proposing",
    "hs_date_entered_closing",
    "hs_date_entered_closed_won",
]

# Fallback: if the above property names don't work, the script
# will still run — those fields will just be null. You can update
# these to the correct internal names from HubSpot > Settings > Properties.
DEAL_PROP_MAP = {
    "created": "createdate",
    "owner": "hubspot_owner_id",
    "segment": "americas_deal_segment",
    "qualifying": "hs_date_entered_qualifying",
    "validating": "hs_date_entered_validating",
    "proposing": "hs_date_entered_proposing",
    "closing": "hs_date_entered_closing",
    "closed_won": "hs_date_entered_closed_won",
}


def parse_deal(record):
    props = record.get("properties", {})
    def g(key):
        return props.get(DEAL_PROP_MAP[key]) or None
    return [
        g("created"), g("qualifying"), g("validating"), g("proposing"),
        g("closing"), g("closed_won"),
        props.get(DEAL_PROP_MAP["segment"], "") or "",
        props.get(DEAL_PROP_MAP["owner"], "") or "",
    ]


def build_deals():
    print("Fetching deals (Sales - Global pipeline)...")
    filters = [{"propertyName": "pipeline", "operator": "EQ", "value": SALES_GLOBAL_PIPELINE}]
    raw = fetch_all("deals", DEAL_PROPERTIES, filters)
    print(f"  Got {len(raw)} deals")
    data = [parse_deal(r) for r in raw]
    data = [d for d in data if d[0]]
    build_html("template-deals.html", "deals.html", "DEALS_RAW", data)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    build_leads()
    print()
    build_deals()
    print("\nDone!")


if __name__ == "__main__":
    main()
