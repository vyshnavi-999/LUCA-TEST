# Voice Capture — Phase 1: record · transcribe · store (no auth)

Validate the three things before the LLM: **profile creation, audio saving, ASR.**
No streaming, no GPU, no LLM, **no passwords/OTP.**

```
Browser (name + phone/email  ->  user_id ;  then mic record)
   -> Backend (FastAPI on EC2)
        -> AWS S3            (audio, private)
        -> Sarvam ASR        (transcript)
        -> AWS RDS Postgres  (users + recordings)
```

IDENTITY: first time = name + phone/email -> profile created. Next time = just the
phone/email -> looked up. No verification (anyone could type any number) — fine for a
data test, not for real security. The browser remembers you so you don't retype.

Do the steps in order. Each has a check.

================================================================
## Part A — Your computer
================================================================
```bash
node --version      # 18+  (for Claude Code)
python3 --version   # 3.10+
unzip voice-phase1.zip
cd voice-phase1
```
Check: `ls` shows backend/ frontend/ README.md CLAUDE.md.

================================================================
## Part B — RDS (database)
================================================================
1. AWS Console -> RDS -> Create database -> PostgreSQL. Free tier, db.t3.micro is fine.
2. Master username `postgres`, set a master password (save it).
3. Initial database name: `voice`.
4. For first testing: Public access = Yes, and add your IP to its security group.
   (Lock down later — see Notes.)
5. Create, wait for Available, copy the endpoint (host).
6. Connection string:
   `postgresql://postgres:YOUR_PASSWORD@YOUR-ENDPOINT:5432/voice`
7. Connect with psql / DBeaver / TablePlus and run:
   ```sql
   create extension if not exists pgcrypto;

   create table users (
     user_id    uuid primary key default gen_random_uuid(),
     name       text,
     identifier text unique not null,   -- phone number OR email (the login key)
     id_type    text,                   -- 'phone' or 'email'
     created_at timestamptz default now()
   );

   create table recordings (
     id              uuid primary key default gen_random_uuid(),
     user_id         uuid not null references users(user_id),
     created_at      timestamptz default now(),
     audio_key       text,
     transcript_text text,
     language        text,
     status          text default 'completed'
                     check (status in ('completed','incomplete','quota_exhausted','error',
                                       'llm_failed','tts_failed')),
     llm_response_text text,
     tokens_used     integer,
     model_version   text,
     reply_audio_key text
   );
   ```

   If upgrading an existing database, run this migration instead:
   ```sql
   alter table recordings add column if not exists llm_response_text text;
   alter table recordings add column if not exists tokens_used integer;
   alter table recordings add column if not exists model_version text;
   alter table recordings add column if not exists reply_audio_key text;
   alter table recordings drop constraint if exists recordings_status_check;
   alter table recordings add constraint recordings_status_check
     check (status in ('completed','incomplete','quota_exhausted','error',
                       'llm_failed','tts_failed'));
   ```
Check: both tables exist; you can connect with the connection string.

================================================================
## Part C — S3 (audio) + IAM (access)
================================================================
1. S3 -> Create bucket. Unique name, your region. **Block ALL public access (keep checked).**
2. Note bucket name + region code (e.g. ap-south-1).
3. IAM -> Policies -> Create (JSON), replace the bucket name:
   ```json
   {"Version":"2012-10-17","Statement":[{"Effect":"Allow",
    "Action":["s3:PutObject","s3:GetObject"],
    "Resource":"arn:aws:s3:::YOUR-BUCKET-NAME/*"}]}
   ```
   Name it `voice-audio-rw`.
4. LOCAL testing: IAM -> Users -> create `voice-local`, attach `voice-audio-rw`,
   create an access key (outside AWS), copy key id + secret.
   (On EC2 you attach `voice-audio-rw` as a ROLE instead — no keys on disk.)
Check: private bucket exists; you have bucket name, region, local access keys.

================================================================
## Part D — Sarvam (ASR)
================================================================
Sign up at sarvam.ai, create an API key, copy it. Keep the speech-to-text docs page
open — you'll hand it to Claude Code to make the call exact.

================================================================
## Part E — Put values in the right place
================================================================
Backend `backend/.env` (copy from .env.example):
```
AWS_REGION=<region, e.g. ap-south-1>
DATABASE_URL=postgresql://postgres:PASSWORD@ENDPOINT:5432/voice
S3_BUCKET=<bucket name>
SARVAM_API_KEY=<key>
ALLOWED_ORIGIN=http://localhost:8080
DAILY_LIMIT=0          # 0 = unlimited for Phase 1; set a number later to switch on
AWS_ACCESS_KEY_ID=<local key id>        # local testing only
AWS_SECRET_ACCESS_KEY=<local secret>    # local testing only
```
Frontend `frontend/index.html` (top of the script): just one line:
```js
const BACKEND_URL = "http://localhost:8000";
```
Rule: the DB URL/password, Sarvam key, and AWS secrets go ONLY in backend/.env.

================================================================
## Part F — Run locally
================================================================
Backend (terminal 1):
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
set -a; source .env; set +a
uvicorn main:app --reload --port 8000
```
Check: http://localhost:8000/healthz -> {"ok":true}

Frontend (terminal 2):
```bash
cd frontend
python3 -m http.server 8080
```
Open http://localhost:8080 (localhost only — the mic is blocked otherwise).

================================================================
## Part G — Test and verify
================================================================
1. Enter a phone/email + a name, Continue.
2. Tap mic, speak, tap to stop. Transcript appears.
3. Verify the three artifacts:
   - RDS `users` table: a row with your name + identifier = profile created.
   - S3 bucket: a file under `<user_id>/...` = audio saved.
   - RDS `recordings` table: a row with your user_id + transcript = ASR worked.
4. Reload the page — you stay "logged in" (browser remembered you).
5. Click "Switch user", enter a DIFFERENT phone/email (no name needed if it already
   exists; a name if new) -> separate user + separate rows = identification works.

================================================================
## Part H — Deploy backend to EC2 (after local works)
================================================================
1. Launch EC2: Ubuntu, t3.small (CPU, no GPU). Attach the `voice-audio-rw` IAM ROLE.
2. Security group: inbound 22 (your IP), 80/443. Allow EC2 -> RDS on 5432.
3. On the instance:
   ```bash
   sudo apt update && sudo apt install -y python3-venv
   # copy the project up (scp/git), then:
   cd voice-phase1/backend
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   # set env WITHOUT AWS keys (the IAM role provides S3):
   #   AWS_REGION, DATABASE_URL, S3_BUCKET, SARVAM_API_KEY, ALLOWED_ORIGIN(=real frontend URL)
   uvicorn main:app --host 0.0.0.0 --port 8000
   ```
4. HTTPS in front (mic needs it): domain + Caddy or nginx+certbot to port 8000.
   Update BACKEND_URL in index.html to the HTTPS URL.
5. Run uvicorn under systemd so it restarts on reboot/crash.
Check: https://your-backend/healthz returns ok.

================================================================
## Notes & honest gotchas
================================================================
- No real auth: identity is self-reported; don't put anything sensitive behind it.
- The S3 folder is the uuid user_id, NOT the phone/email — keeps PII out of object keys.
- Lock down RDS after testing (private, reachable only from the EC2 security group).
- Keep S3 private; on EC2 use the role, never keys.
- Audio is WebM/Opus. If Sarvam rejects it, add an ffmpeg convert to WAV, or switch ASR.
- `status`: completed | incomplete | quota_exhausted | error. The quota check IS wired:
  set DAILY_LIMIT (env) to a number to cap completed recordings per user per 24h; 0 = off.
  When over the limit, the request is blocked before S3/ASR and logged as quota_exhausted.
- Still sends audio to Sarvam (third party). Full privacy is later. Say so in consent text.
