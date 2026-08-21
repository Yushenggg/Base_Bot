from core.auth import register_provider
from core.auth.flows import DeviceCodeProvider

register_provider(
    DeviceCodeProvider(
        provider_id="google",
        display_name="Google",
        client_id_env="GOOGLE_CLIENT_ID",
        client_secret_env="GOOGLE_CLIENT_SECRET",
        device_code_url="https://oauth2.googleapis.com/device/code",
        token_url="https://oauth2.googleapis.com/token",
        scopes_default=["openid", "https://www.googleapis.com/auth/userinfo.email"],
        scopes_supported=[
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile",
            "https://www.googleapis.com/auth/calendar.readonly",
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/drive.readonly",
            "https://www.googleapis.com/auth/drive.file",
            "https://www.googleapis.com/auth/tasks",
            "https://www.googleapis.com/auth/contacts.readonly",
        ],
        extra_device_code_params={"access_type": "offline", "prompt": "consent"},
        rotate_refresh_tokens=True,
        setup_urls=[
            (
                "Google Cloud Console — APIs & Services",
                "https://console.cloud.google.com/apis/library",
            ),
            (
                "OAuth consent screen",
                "https://console.cloud.google.com/apis/credentials/consent",
            ),
            (
                "Create OAuth client ID",
                "https://console.cloud.google.com/apis/credentials",
            ),
        ],
        setup_instructions=(
            "1. Open the Google Cloud Console and create a new project (or pick an existing one).\n"
            "2. Go to APIs & Services → Library. Search for and Enable each API you need\n"
            "   (e.g. Google Calendar API, Gmail API, Drive API, Tasks API).\n"
            "3. Go to APIs & Services → OAuth consent screen.\n"
            "   - User type: External\n"
            "   - Fill in app name, your support email, and your developer email → Save and Continue\n"
            "   - Scopes step: skip (we request scopes per-login) → Save and Continue\n"
            "   - Test users step: add your own Gmail address → Save and Continue\n"
            "4. Go to APIs & Services → Credentials → Create Credentials → OAuth client ID.\n"
            "   - Application type: Desktop app\n"
            "   - Name: anything (e.g. 'TeleBaseBot')\n"
            "   - Click Create\n"
            "5. In the dialog that appears, copy the Client ID and Client Secret.\n"
            "6. Put them in .env as GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET, then /restart_bot.\n"
            "\n"
            "Verification is NOT required for personal use — Google lets you have up to 100\n"
            "test users in 'External' mode without submitting for verification, and you're\n"
            "user #1. The OAuth flow will work indefinitely for your account."
        ),
        revoke_url="https://oauth2.googleapis.com/revoke",
    ),
)
