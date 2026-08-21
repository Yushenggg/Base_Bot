# Connecting Google (Calendar, Gmail, Drive, etc.)

Provider-specific setup for Google. Covers Google Calendar, Gmail,
Drive, Tasks, Contacts, and any other Google API that uses standard
Google OAuth.

## What "connecting" means

When you connect your Google account, the bot can call Google APIs as
if it were you. To make this work without giving the bot your Google
password, OAuth (the "Sign in with Google" protocol) is used:

- You visit Google on your own device and click "Allow"
- Google gives the bot a token instead of your password
- The bot uses that token to call APIs on your behalf
- You can revoke the token at any time from your Google account settings

The bot never sees your Google password.

## How the chat flow works

Once Google is registered in the bot, you'll see `/login_google` in
the Telegram menu. The flow:

```
You:    /login_google

Bot:    First-time setup for Google.
        [walks you through getting an OAuth app at Google Cloud Console]
        Paste your Client ID here.

You:    123456789-abc...xyz.apps.googleusercontent.com
        [the bot deletes your message immediately]

Bot:    Got it. Now paste your Client Secret.

You:    GOCSPX-...
        [the bot deletes your message immediately]

Bot:    Stored. Now approve access on your phone:
        Open https://google.com/device, enter code WDJB-MJHT,
        and click Allow.

You:    [open the URL on your phone, type the code, click Allow]

Bot:    Logged in. Try /cal_this_week or whatever tool you wired up.
```

Subsequent logins (after token expiry, on a new device, etc.) skip the
client_id/secret steps — those are already saved. You go straight to the
phone-approval step.

## Step 1: Create a Google Cloud project

1. Open https://console.cloud.google.com/projectcreate
2. Project name: anything (e.g. `telebasebot`)
3. Click **Create**

## Step 2: Enable the APIs you need

1. Open https://console.cloud.google.com/apis/library
2. For each API you want to use:
   - Search for it (e.g. "Google Calendar API")
   - Click on it
   - Click the blue **Enable** button
3. Common ones:

   | API | URL slug | Use it for |
   |---|---|---|
   | Google Calendar API | `calendar-json.googleapis.com` | Read/create events |
   | Gmail API | `gmail.googleapis.com` | Read/send email |
   | Google Drive API | `drive.googleapis.com` | Read/write files |
   | Google Tasks API | `tasks.googleapis.com` | Task lists |
   | People API | `people.googleapis.com` | Contacts |

## Step 3: Configure the consent screen

1. Open https://console.cloud.google.com/apis/credentials/consent
2. Click **Get started** (or "Configure consent screen" if you've done this before)
3. Fill in:
   - **App name**: anything (e.g. `MyBot`)
   - **User support email**: your Gmail address
   - **Developer contact information**: your Gmail address
4. Click **Save and Continue** through the next two screens (Scopes and
   Test users). You can skip everything — the bot requests scopes per-login.
5. On the Test users screen, click **Add users** and add your own Gmail
6. Click **Save and Continue**, then **Back to Dashboard**

> **You don't need to submit for verification.** Google's "External"
> mode lets up to 100 test users use the OAuth flow without verification.
> You're user #1. This works indefinitely for personal use.

## Step 4: Create an OAuth client

1. Open https://console.cloud.google.com/apis/credentials
2. Click **+ Create Credentials** → **OAuth client ID**
3. **Application type**: **Desktop app**
4. **Name**: anything (e.g. `TeleBaseBot`)
5. Click **Create**
6. A popup appears with your **Client ID** and **Client Secret**. Copy both.

## Step 5: Get the credentials into the bot

You have two options:

**Option A (recommended for most users): just paste them in Telegram.**

The bot will prompt you for them during `/login_google` and store them
encrypted on the server. Your chat messages are deleted immediately after
capture — they don't sit in your chat history.

**Option B (if you prefer not to chat secrets): add them to `.env` manually.**

Edit `.env` in the project directory and add:

```dotenv
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-your-secret
```

Then run `/restart_bot` in Telegram.

## Step 6: Run `/login_google`

The bot will:
1. (If using Option A) ask you to paste the credentials
2. Generate a one-time code (like `WDJB-MJHT`)
3. Show you the URL `https://google.com/device` to visit

Open that URL on any device (phone, laptop, anywhere), sign in to the
Google account you want to connect, type the code, and click **Allow**.

You're done. The bot will confirm and you can start using whatever tool
you wired up (e.g. `/cal_this_week` for Google Calendar).

## Common Google scopes

The bot supports these scopes out of the box. Pick the ones you actually
need — fewer is more secure.

| Scope | What it allows |
|---|---|
| `openid` | Basic identity (always requested) |
| `https://www.googleapis.com/auth/userinfo.email` | Read your email address |
| `https://www.googleapis.com/auth/userinfo.profile` | Read your name and profile |
| `https://www.googleapis.com/auth/calendar.readonly` | Read your calendars |
| `https://www.googleapis.com/auth/calendar.events` | Read/write events |
| `https://www.googleapis.com/auth/calendar` | Full calendar access |
| `https://www.googleapis.com/auth/gmail.readonly` | Read your email |
| `https://www.googleapis.com/auth/gmail.send` | Send email as you |
| `https://www.googleapis.com/auth/gmail.modify` | Read + send + modify labels |
| `https://www.googleapis.com/auth/drive.readonly` | Read your Drive files |
| `https://www.googleapis.com/auth/drive.file` | Read/write files the bot created |
| `https://www.googleapis.com/auth/tasks` | Read/write your tasks |
| `https://www.googleapis.com/auth/contacts.readonly` | Read your contacts |

If you need a scope that's not in this list, ask the bot developer to add
it to `core/auth/providers/google.py` `scopes_supported`.

## What if it fails?

| Error | Likely cause | Fix |
|---|---|---|
| `400 invalid_client` | Wrong Client ID/Secret | Re-check the values from Google Cloud Console |
| `403 access_denied` | You didn't add yourself as a test user | Go back to OAuth consent screen → Test users → add your email |
| `403 org_internal` | You picked "Internal" user type instead of "External" | You need External for personal Gmail accounts |
| `403 email_not_verified` | Your Google account email isn't verified | Verify your email at https://myaccount.google.com/email |
| `400 invalid_scope` | The bot asked for a scope Google doesn't recognize for this app | Check `scopes_supported` in `core/auth/providers/google.py` |
| No refresh token in response | Missing `access_type=offline` | This is built-in; if it happens, report it as a bug |
| Bot says `not configured` | No provider registered for this name | Ask the bot developer to add `core/auth/providers/google.py` and restart |
| Token expired mid-tool-call | Refresh token revoked or expired (>6 months idle) | Run `/login_google` again — same one-click flow |

## Logging out

To disconnect:

```
/logout_google
```

This deletes the encrypted tokens from the bot's disk.

To also revoke Google's record of the grant:

1. Open https://myaccount.google.com/connections
2. Find "TeleBaseBot" (or whatever you named it) under "Third-party apps"
3. Click it → **Remove access**

After revocation, the bot cannot log back in even with the stored
credentials — you'd have to do the full setup again.

## Security notes

- The bot stores your Google tokens **encrypted** on disk
  (`data/auth/google.json.enc`). The encryption key is in `.env`.
- Your Telegram chat messages containing Client ID/Secret are deleted
  by the bot right after capture — they're not in your history.
- The encryption key only protects against disk theft. If someone has
  both `.env` and `data/auth/`, they can decrypt your tokens. Keep both
  secure.
- Refresh tokens are long-lived (months) and powerful. Treat them like
  passwords — never share them, never paste them anywhere public.
- If you suspect a leak, run `/logout_google` AND revoke from
  https://myaccount.google.com/connections.

## Need a different provider?

Other providers (Microsoft, GitHub, Notion, etc.) follow the same
pattern but have their own setup walkthroughs. Ask the bot developer
to add `core/auth/providers/<name>.py` and a matching
`docs/user-auth-<name>.md`.
