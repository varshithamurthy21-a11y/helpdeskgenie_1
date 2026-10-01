"""Create HelpDeskGenie demo runbooks in your Confluence space.

Run once on your own computer after creating the space:

    python seed_confluence.py --site https://YOUR-SITE.atlassian.net --email you@example.com --space ITKB

It asks for your Atlassian API token (nothing is typed on screen or saved).
By default it adds runbooks the app's built-in knowledge base does NOT have, so
you can see HelpDeskGenie fall back to Confluence over MCP. Add --include-core to
also copy the 12 built-in runbooks. Pages that already exist are skipped.
"""
import argparse
import getpass
import html
import os
import sys

from integrations import AtlassianError, ConfluenceClient

EXTRA_RUNBOOKS = [
    {"title": "Hardware Replacement: Damaged Laptop or Screen", "labels": ["cat-hardware", "laptop", "screen", "broken", "cracked"],
     "steps": ["Stop using the device if the screen is cracked or the battery is swollen.",
               "Back up any local files to OneDrive if the laptop still works.",
               "Log a Hardware ticket with the asset tag from the sticker under the laptop.",
               "Collect a loaner laptop from the IT desk on the ground floor (bring your ID badge).",
               "Return the damaged device in its charger and bag; IT wipes it before repair."]},
    {"title": "Slow Internet or Network Performance", "labels": ["cat-networking", "slow", "internet", "speed", "latency"],
     "steps": ["Run a speed test at https://speed.company.internal and note download, upload and ping.",
               "Close large downloads, cloud backups and video streams running in the background.",
               "If on Wi-Fi, move closer to the access point or use a wired port.",
               "If several people on your floor are affected, log a P2 Networking ticket with the speed results."]},
    {"title": "Core Network Change Process (BGP, Firewalls, Routers)", "labels": ["cat-networking", "critical", "bgp", "firewall", "router", "core"],
     "steps": ["Changes to core routers, firewalls or BGP are never made through self-service.",
               "Raise a Change Request in the CAB queue with the business reason and a rollback plan.",
               "The Network team reviews it at the weekly Change Advisory Board meeting.",
               "Approved changes are scheduled in the Sunday 02:00 maintenance window."]},
    {"title": "Lost or Stolen Laptop or Phone", "labels": ["cat-identity", "critical", "lost", "stolen", "device"],
     "steps": ["Report it immediately; time matters for protecting company data.",
               "Log a P1 Identity ticket so IT can lock and remotely wipe the device.",
               "Change your password from another device as soon as possible.",
               "If it was stolen, file a police report and attach the reference number to the ticket."]},
    {"title": "New Joiner Laptop Setup", "labels": ["cat-hardware", "new", "joiner", "onboarding", "setup"],
     "steps": ["Sign in with the temporary password from your welcome email; you will be asked to change it.",
               "Set up multi-factor authentication at https://mysignins.company.internal.",
               "Open Company Portal and install the Required apps group.",
               "Map the department shared drive and check that Outlook and Teams sign in."]},
]


def page_html(steps):
    items = "".join(f"<li>{html.escape(s)}</li>" for s in steps)
    return f"<p>HelpDeskGenie runbook. Each numbered step is quoted to users exactly as written.</p><ol>{items}</ol>"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", required=True, help="https://YOUR-SITE.atlassian.net")
    ap.add_argument("--email", required=True, help="the email you sign in to Atlassian with")
    ap.add_argument("--space", default="ITKB", help="Confluence space key (default ITKB)")
    ap.add_argument("--include-core", action="store_true", help="also copy the 12 built-in runbooks")
    a = ap.parse_args()
    token = os.environ.get("ATLASSIAN_API_TOKEN") or getpass.getpass("Atlassian API token (hidden): ").strip()
    cf = ConfluenceClient(a.site, a.email, token)

    pages = list(EXTRA_RUNBOOKS)
    if a.include_core:
        from data import KB_ARTICLES
        pages += [{"title": k["title"], "labels": ["cat-" + k["category"].lower()] + (["critical"] if k.get("critical") else []),
                   "steps": k["steps"]} for k in KB_ARTICLES]
    made = skipped = 0
    for p in pages:
        try:
            if cf.find_page(a.space, p["title"]):
                print(f"  skip   {p['title']} (already there)")
                skipped += 1
                continue
            page = cf.create_page(a.space, p["title"], page_html(p["steps"]), p["labels"])
            print(f"  added  {p['title']}  ->  {cf.base}{page.get('_links', {}).get('webui', '')}")
            made += 1
        except AtlassianError as e:
            sys.exit(f"Stopped: {e}\nCheck the site URL, email, token, and that space '{a.space}' exists.")
    print(f"Done: {made} added, {skipped} already there.")


if __name__ == "__main__":
    main()
