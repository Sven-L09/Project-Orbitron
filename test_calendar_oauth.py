#!/usr/bin/env python3
"""Test Google Calendar API with OAuth2 client credentials."""
import json
import os
import sys
from datetime import datetime, timezone, timedelta

# Try google-auth first, fallback to manual flow
try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    USE_GOOGLE_LIB = True
except ImportError:
    USE_GOOGLE_LIB = False
    print("⚠️  google-auth libs not installed, will use manual HTTP flow")

SCOPES = ["https://www.googleapis.com/auth/calendar"]
TOKEN_FILE = "/home/svenf/Dokumente/Informatik/Dev/Project-Orbitron/test_token.json"

CLIENT_CONFIG = {
    "installed": {
        "client_id": "os.environ.get("GOOGLE_CLIENT_ID", "")",
        "project_id": "os.environ.get("GOOGLE_PROJECT_ID", "")",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_secret": "os.environ.get("GOOGLE_CLIENT_SECRET", "")",
        "redirect_uris": ["http://localhost"]
    }
}

def get_credentials():
    """Get OAuth2 credentials, refreshing or authorizing as needed."""
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("🔄 Refreshing expired token...")
            creds.refresh(Request())
        else:
            print("🔐 Opening browser for authorization...")
            flow = InstalledAppFlow.from_client_config(CLIENT_CONFIG, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
        print("✅ Token saved")
    return creds


def main():
    print("=" * 55)
    print("  Google Calendar OAuth2 Test")
    print("  Datum: 24. Mai 2026, 20:00")
    print("=" * 55)

    if not USE_GOOGLE_LIB:
        print("❌ Bitte installieren: pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client")
        sys.exit(1)

    # 1) Auth
    print("\n[1/4] Authentifizierung...")
    creds = get_credentials()
    service = build("calendar", "v3", credentials=creds)
    print("✅ Authentifizierung erfolgreich!")

    # 2) Kalenderliste lesen
    print("\n[2/4] Kalenderliste lesen...")
    cal_list = service.calendarList().list().execute()
    for cal in cal_list.get("items", []):
        print(f"  📅 {cal['summary']} (ID: {cal['id']})")

    # 3) Termin erstellen: 24. Mai 2026, 20:00-21:00
    print("\n[3/4] Termin erstellen (24.05.2026 20:00)...")
    event_body = {
        "summary": "🚀 Orbitron Test-Termin",
        "description": "Automatischer Test – kann gelöscht werden",
        "start": {
            "dateTime": "2026-05-24T20:00:00+02:00",
            "timeZone": "Europe/Berlin",
        },
        "end": {
            "dateTime": "2026-05-24T21:00:00+02:00",
            "timeZone": "Europe/Berlin",
        },
    }
    created = service.events().insert(calendarId="primary", body=event_body).execute()
    event_id = created["id"]
    print(f"✅ Termin erstellt! ID: {event_id}")
    print(f"   Link: {created.get('htmlLink')}")

    # 4) Termin wieder lesen
    print("\n[4/4] Termin lesen...")
    read_back = service.events().get(calendarId="primary", eventId=event_id).execute()
    print(f"✅ Termin gelesen: {read_back['summary']}")
    start = read_back["start"]["dateTime"]
    end = read_back["end"]["dateTime"]
    print(f"   Von: {start}  Bis: {end}")

    # Cleanup
    print("\n🧹 Test-Termin wird gelöscht...")
    service.events().delete(calendarId="primary", eventId=event_id).execute()
    print("✅ Gelöscht!")

    print("\n" + "=" * 55)
    print("  ✅ ALLE TESTS BESTANDEN!")
    print("=" * 55)

    # Cleanup token file
    if os.path.exists(TOKEN_FILE):
        os.remove(TOKEN_FILE)
        print("🧹 Test-Token-Datei entfernt")


if __name__ == "__main__":
    main()