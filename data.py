"""Seed data for HelpDeskGenie.

In production these come from Confluence (runbooks), JIRA (resolved tickets) and
AD/LDAP (users). Here they are local fixtures so the demo and the evaluation
suite are deterministic.

Every KB article carries its remediation steps as discrete strings. The agent
only ever returns these strings (never free-generated text), which is what makes
answers "hallucination-controlled": each step in a reply can be traced back to
one article.
"""

CONFLUENCE = "https://confluence.company.internal/display/ITKB"

# ---------------------------------------------------------------------------
# Knowledge base (Confluence runbooks + policies)
# ---------------------------------------------------------------------------
KB_ARTICLES = [
    {
        "id": "KB101",
        "title": "VPN Disconnection and Troubleshooting",
        "category": "Networking",
        "tags": "vpn disconnect disconnecting drops dropping keeps disconnecting tunnel globalprotect anyconnect remote home connection lost",
        "critical": False,
        "steps": [
            "Check that your internet connection works without the VPN (open any external website).",
            "Flush your DNS cache: open a terminal and run `ipconfig /flushdns`.",
            "Make sure UDP ports 500 and 4500 are not blocked by your router or firewall.",
            "Disconnect the VPN client, wait 10 seconds, and reconnect.",
        ],
        # Clarifying question: the right steps depend on where the user is.
        "clarify": {
            "question": "Are you connecting from **home / remote**, or are you on the **office network**?",
            "variants": {
                "home": {
                    "match": ["home", "remote", "wfh", "hotel", "hotspot", "outside", "external"],
                    "steps": [
                        "Check that your home internet works without the VPN (open any external website).",
                        "Flush your DNS cache: open a terminal and run `ipconfig /flushdns`.",
                        "Make sure UDP ports 500 and 4500 are not blocked by your home router.",
                        "If you are on public Wi-Fi or a hotel network, switch to a mobile hotspot; those networks often block IPsec.",
                        "Disconnect the VPN client, wait 10 seconds, and reconnect.",
                    ],
                },
                "office": {
                    "match": ["office", "onsite", "on-site", "campus", "desk", "corp", "building", "floor"],
                    "steps": [
                        "You do not need the VPN on the office network. Disconnect the VPN client.",
                        "Connect to the `Corp-Secure` Wi-Fi or a wired port instead.",
                        "If internal sites still fail, flush DNS with `ipconfig /flushdns`.",
                    ],
                },
            },
            # Only ask if none of these words already tell us the location.
        },
        "tip": "A VPN is the secure tunnel that lets you reach company systems from outside the office.",
        "expert": "Flush DNS (`ipconfig /flushdns`), confirm UDP 500/4500 open, reconnect client.",
    },
    {
        "id": "KB102",
        "title": "Mapping Corporate Network Drives",
        "category": "Storage",
        "tags": "map network drive mapped drive shared drive file share unc path storage department folder",
        "critical": False,
        "steps": [
            "Make sure you are on the office network or connected to the VPN.",
            "Open File Explorer and select **This PC**.",
            "Click **Map network drive** in the toolbar.",
            "Pick a drive letter and enter the path `\\\\storage.internal\\shared\\departments`.",
            "Tick **Reconnect at sign-in** and click **Finish**.",
        ],
        "tip": "A network drive is a shared folder on a company server that shows up like a local disk.",
        "expert": "Map `\\\\storage.internal\\shared\\departments` (VPN or office LAN required).",
    },
    {
        "id": "KB103",
        "title": "Outlook Exchange Sync Issues",
        "category": "Applications",
        "tags": "outlook email emails mail not syncing sync exchange inbox not updating send receive ost mailbox",
        "critical": False,
        "steps": [
            "Confirm you are online (check the status bar in Outlook says **Connected to Microsoft Exchange**).",
            "Go to **File -> Account Settings -> Account Settings**, select your account and choose **Repair**.",
            "If mail still does not update, close Outlook and rename your `.ost` file so Outlook rebuilds it on next start.",
        ],
        "tip": "Outlook keeps a local copy of your mailbox; rebuilding it forces a fresh download from the server.",
        "expert": "Repair the account profile; if still stale, rename the OST to force a rebuild.",
    },
    {
        "id": "KB104",
        "title": "Wi-Fi Authentication Failures",
        "category": "Networking",
        "tags": "wifi wi-fi wireless authentication failed keeps dropping corp-secure ssid dhcp cannot connect",
        "critical": False,
        "steps": [
            "Forget the `Corp-Secure` network in your Wi-Fi settings.",
            "Renew your IP address: open a terminal and run `ipconfig /release` then `ipconfig /renew`.",
            "Reconnect to `Corp-Secure` and sign in with your corporate credentials.",
        ],
        "tip": "Forgetting the network clears saved settings that can go stale after a password change.",
        "expert": "Forget `Corp-Secure`, release/renew DHCP lease, re-authenticate.",
    },
    {
        "id": "KB105",
        "title": "Shared Network Folder Access Denied",
        "category": "Storage",
        "tags": "access denied shared folder permission error share cannot open folder security group token",
        "critical": False,
        "steps": [
            "Sign out of Windows and sign back in to refresh your security group token.",
            "If you still see **Access Denied**, your AD group membership may have expired.",
            "Ask me to raise an access request for the folder; it will be routed to the folder owner for approval.",
        ],
        "tip": "Your access to shared folders comes from the security groups your account belongs to.",
        "expert": "Refresh the Kerberos token (re-logon); if still denied, raise an AD group access request.",
    },
    {
        "id": "KB106",
        "title": "Microsoft Teams Audio Device Settings",
        "category": "Applications",
        "tags": "teams audio microphone mic speaker headset sound call meeting cannot hear device",
        "critical": False,
        "steps": [
            "Close other apps that might be using your microphone (Zoom, browser tabs, recorders).",
            "In Teams, go to **Settings -> Devices** and select the correct speaker and microphone.",
            "Click **Make a test call** to confirm audio works.",
        ],
        "tip": "Only one app can use a headset microphone reliably at a time.",
        "expert": "Release the audio device from other apps, reselect it under Settings -> Devices.",
    },
    {
        "id": "KB107",
        "kind": "policy",
        "title": "Corporate Password Policy",
        "category": "Identity",
        "tags": "password policy requirements length complexity expire expiry rotation how often change rules characters",
        "critical": True,
        "steps": [
            "Passwords must be at least 14 characters long.",
            "Passwords expire every 90 days; you will be reminded 14 days before expiry.",
            "Your last 12 passwords cannot be reused.",
            "Never share your password, including with IT. IT staff will never ask for it.",
        ],
        "tip": "A long passphrase (four random words) is easier to remember and meets the policy.",
        "expert": "14+ chars, 90-day expiry, 12-password history, never share.",
    },
    {
        "id": "KB108",
        "title": "Software Installation Requests",
        "category": "Applications",
        "tags": "install software application program new app licence license install request company portal download",
        "critical": False,
        "steps": [
            "Open **Company Portal** from the Start menu.",
            "Search for the application. Approved software can be installed directly from there.",
            "If the software is not listed, ask me to raise an access request with the software name; it needs manager approval.",
        ],
        "tip": "Company Portal only shows software that security has already approved.",
        "expert": "Self-serve from Company Portal; unlisted software needs an approval request.",
    },
    {
        "id": "KB109",
        "kind": "policy",
        "title": "Access Request Procedure",
        "category": "Access",
        "tags": "access request procedure how to request permission get access system application role approval",
        "critical": True,
        "steps": [
            "Tell me the system or resource you need and why.",
            "I raise an access request and route it to the resource owner or your manager.",
            "Access is granted only after the approver signs off. You will get a notification either way.",
        ],
        "tip": "Access is never granted automatically; a human approver always signs off.",
        "expert": "Raise request -> routed to resource owner -> granted after approval.",
    },
    {
        "id": "KB110",
        "title": "Account Lockout Self-Service",
        "category": "Identity",
        "tags": "account locked out lockout too many attempts cannot log in sign in unlock self service",
        "critical": True,
        "steps": [
            "Accounts lock after 5 failed sign-in attempts.",
            "You can unlock it yourself by asking me; I will send a one-time code to your registered phone.",
            "Enter the code here to verify your identity; your account is then unlocked.",
        ],
        "tip": "The one-time code proves it is really you before anything changes on your account.",
        "expert": "Self-service unlock via OTP to the registered device.",
    },
    {
        "id": "KB111",
        "title": "Printer Not Printing",
        "category": "Hardware",
        "tags": "printer print printing stuck queue jam cannot print follow me badge",
        "critical": False,
        "steps": [
            "Check the printer display for paper jams or empty trays.",
            "Open **Settings -> Printers**, open the queue and cancel any stuck jobs.",
            "Re-send your document to the `FollowMe` queue and release it with your badge.",
        ],
        "tip": "Print jobs wait in the FollowMe queue until you tap your badge at any printer.",
        "expert": "Clear the local spooler queue, resend to FollowMe.",
    },
    {
        "id": "KB112",
        "title": "Setting Up Multi-Factor Authentication",
        "category": "Identity",
        "tags": "mfa multi factor authenticator app new phone two factor 2fa setup enroll register device",
        "critical": True,
        "steps": [
            "Go to `https://mysignins.company.internal` from a company device.",
            "Choose **Security info -> Add method -> Authenticator app**.",
            "Scan the QR code with the Authenticator app and approve the test notification.",
            "Got a new phone and lost the old one? Log a ticket; IT must verify you in person before re-registering.",
        ],
        "tip": "MFA means a second check (your phone) on top of your password.",
        "expert": "Register via mysignins -> Security info; lost device needs in-person re-verification.",
    },
]

# Past resolved-ticket summaries. They are retrievable too, so the agent can say
# "this was fixed before by...". Only resolution text written by IT is used.
RESOLVED_TICKET_SUMMARIES = [
    {
        "id": "JIRA-3301",
        "title": "Resolved: VPN drops every 10 minutes on home fibre router",
        "category": "Networking",
        "tags": "vpn drops disconnect home router fibre ipsec",
        "critical": False,
        "steps": ["The router's SIP ALG / IPsec passthrough setting was blocking the tunnel. Enabling IPsec passthrough on the home router fixed it."],
        "tip": "", "expert": "Enable IPsec passthrough on the home router.",
    },
    {
        "id": "JIRA-3877",
        "title": "Resolved: Outlook stuck on 'Updating inbox' after mailbox migration",
        "category": "Applications",
        "tags": "outlook stuck updating inbox migration sync",
        "critical": False,
        "steps": ["Creating a new Outlook profile (Control Panel -> Mail -> Show Profiles -> Add) resolved the sync issue."],
        "tip": "", "expert": "Recreate the Outlook profile.",
    },
]

# Resource -> owner used when routing access requests.
RESOURCE_OWNERS = {
    "finance share": "mgr_finance",
    "hr share": "mgr_hr",
    "salesforce": "owner_crm",
    "github": "owner_eng",
    "jira admin": "owner_itsm",
    "production database": "owner_dba",
    "aws": "owner_cloud",
    "tableau": "owner_bi",
}

# Directory (AD/LDAP stand-in).
USERS = {
    "user123": {"name": "Asha Rao", "manager": "mgr_eng", "phone": "+91 98xxxx1234", "locked": True, "role": "employee"},
    "user456": {"name": "Rahul Menon", "manager": "mgr_sales", "phone": "+91 98xxxx4456", "locked": False, "role": "employee"},
    "user789": {"name": "Priya Iyer", "manager": "mgr_finance", "phone": "+91 98xxxx7789", "locked": True, "role": "employee"},
    "admin01": {"name": "IT Admin", "manager": "mgr_it", "phone": "+91 98xxxx0001", "locked": False, "role": "it_admin"},
}

SEED_TICKETS = [
    {"ticket_id": "JIRA-4122", "user_id": "user789", "category": "Networking", "priority": "P3", "status": "Resolved",
     "description": "VPN dropouts on home wifi", "resolution_type": "manual", "created_days_ago": 20},
    {"ticket_id": "JIRA-4190", "user_id": "user789", "category": "Networking", "priority": "P3", "status": "Resolved",
     "description": "VPN disconnects again during calls", "resolution_type": "manual", "created_days_ago": 9},
    {"ticket_id": "JIRA-5512", "user_id": "user456", "category": "Applications", "priority": "P3", "status": "Open",
     "description": "Outlook completely disconnected from host", "resolution_type": None, "created_days_ago": 3},
    {"ticket_id": "JIRA-5530", "user_id": "user456", "category": "Applications", "priority": "P2", "status": "Escalated",
     "description": "Outlook not syncing shared calendar", "resolution_type": "escalated", "created_days_ago": 2},
    {"ticket_id": "JIRA-1928", "user_id": "user123", "category": "Identity", "priority": "P3", "status": "Resolved",
     "description": "Account unlock via verified self-service", "resolution_type": "auto", "created_days_ago": 15},
    {"ticket_id": "JIRA-5601", "user_id": "user123", "category": "Hardware", "priority": "P4", "status": "Open",
     "description": "Printer on 3rd floor not printing", "resolution_type": None, "created_days_ago": 1},
]
