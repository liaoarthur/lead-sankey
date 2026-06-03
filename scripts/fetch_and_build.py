#!/usr/bin/env python3
"""
Fetch US leads from HubSpot API and rebuild the Sankey dashboard HTML.

Requires HUBSPOT_API_KEY env var (private app access token).
"""

import os
import sys
import json
import urllib.request
import urllib.parse
from datetime import datetime

HUBSPOT_API_KEY = os.environ.get("HUBSPOT_API_KEY")
if not HUBSPOT_API_KEY:
    print("ERROR: HUBSPOT_API_KEY env var not set")
    sys.exit(1)

# HubSpot CRM Search API
SEARCH_URL = "https://api.hubapi.com/crm/v3/objects/leads/search"
PROPERTIES = [
    "createdate",
    "hs_lead_name",
    "hs_lead_trigger",
    "hs_date_entered_new",
    "hs_date_entered_attempting",
    "hs_date_entered_connected",
    "hs_date_entered_pre_qualified",
    "hs_date_entered_qualified",
]

# Property names may differ — these are common patterns for lead pipeline stage dates.
# If your HubSpot uses different internal names, update the PROP_MAP below.
PROP_MAP = {
    "created": "createdate",
    "trigger": "hs_lead_trigger",
    "new": "hs_date_entered_new",
    "attempting": "hs_date_entered_attempting",
    "connected": "hs_date_entered_connected",
    "prequalified": "hs_date_entered_pre_qualified",
    "qualified": "hs_date_entered_qualified",
}


def hubspot_search(after=None):
    """Search leads with pagination."""
    body = {
        "limit": 100,
        "properties": PROPERTIES,
        "sorts": [{"propertyName": "createdate", "direction": "ASCENDING"}],
    }
    if after:
        body["after"] = after

    data = json.dumps(body).encode()
    req = urllib.request.Request(
        SEARCH_URL,
        data=data,
        headers={
            "Authorization": f"Bearer {HUBSPOT_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def fetch_all_leads():
    """Paginate through all leads."""
    all_leads = []
    after = None
    page = 0
    while True:
        page += 1
        print(f"  Fetching page {page}...")
        result = hubspot_search(after)
        results = result.get("results", [])
        all_leads.extend(results)
        paging = result.get("paging", {})
        next_page = paging.get("next", {})
        after = next_page.get("after")
        if not after or not results:
            break
    return all_leads


def parse_lead(lead):
    """Extract the fields we need from a HubSpot lead object."""
    props = lead.get("properties", {})

    def get_dt(key):
        val = props.get(PROP_MAP[key])
        if val:
            # HubSpot returns ISO timestamps
            return val
        return None

    return [
        get_dt("created"),
        get_dt("new"),
        get_dt("attempting"),
        get_dt("connected"),
        get_dt("prequalified"),
        get_dt("qualified"),
        props.get(PROP_MAP["trigger"], ""),
    ]


def build_html(leads_data):
    """Read the template and inject the data."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(script_dir, "..", "template.html")
    output_path = os.path.join(script_dir, "..", "index.html")

    with open(template_path) as f:
        template = f.read()

    data_js = "const LEADS_RAW = " + json.dumps(leads_data) + ";"
    html = template.replace("%%DATA_PLACEHOLDER%%", data_js)

    with open(output_path, "w") as f:
        f.write(html)

    print(f"  Written index.html ({len(leads_data)} leads, {os.path.getsize(output_path) // 1024} KB)")


def main():
    print("Fetching leads from HubSpot...")
    raw_leads = fetch_all_leads()
    print(f"  Got {len(raw_leads)} leads")

    leads_data = [parse_lead(l) for l in raw_leads]
    # Filter out leads with no created date
    leads_data = [l for l in leads_data if l[0]]

    print("Building HTML...")
    build_html(leads_data)
    print("Done!")


if __name__ == "__main__":
    main()
