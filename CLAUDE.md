# CLAUDE.md — standing instructions for this project

You are building **Phase 1** of a voice data-collection app. Read fully before acting.

## Goal of this phase
Validate three things: (1) user profile creation, (2) audio saving, (3) ASR.
NO LLM, NO streaming, NO authentication in this phase.

## Identity model (self-identification, NOT verified)
- First visit: user enters a NAME + a PHONE or EMAIL. Backend creates a `users` row and
  generates a uuid `user_id`. The phone/email is the unique login key.
- Return visit: user enters only the phone/email; backend looks up the existing user_id.
- No password, no OTP, no token. The browser remembers the user_id in localStorage.
- This is trust-the-client: anyone could type any number. Acceptable for a data test only.

## Stack — AWS
- Database : AWS RDS (PostgreSQL)  -> tables `users` and `recordings`
- Audio    : AWS S3 (private bucket), via boto3. S3 folder = the uuid user_id (NOT the phone).
- ASR      : Sarvam API
- Backend  : FastAPI on AWS EC2 (CPU only, no GPU this phase)

Flow:
Browser (name+phone/email -> /login -> user_id ; then mic record)
  -> FastAPI backend (-> S3 audio, -> Sarvam transcript, -> RDS recordings row)

Reference code is in this folder (backend/, frontend/index.html, README.md). Extend it.
Do NOT reinvent the architecture.

## Schema (already in README)
users(user_id uuid pk, name, identifier unique, id_type, created_at)
recordings(id uuid pk, user_id -> users, created_at, audio_key, transcript_text,
           language, status)
status allowed values: 'completed' | 'incomplete' | 'quota_exhausted' | 'error'
quota_exhausted IS wired: env DAILY_LIMIT = max completed recordings/user/24h, checked
BEFORE any S3/ASR work; 0 = unlimited (Phase 1 default, real number set later).

## Hard rules
- Secrets (DATABASE_URL with password, SARVAM_API_KEY, any AWS keys) ONLY in backend/.env.
  Frontend gets only BACKEND_URL. Ensure .env is gitignored.
- On EC2, S3 access via attached IAM ROLE (no keys on disk). S3 bucket must be PRIVATE.
- Use the uuid user_id as the S3 folder, never the raw phone/email (keep PII out of keys).
- Save audio to S3 BEFORE calling ASR, so the recording survives ASR failure.
- Keep ALL ASR logic in the single `transcribe()` function (swappable later).
- Do NOT add WebSockets, streaming, VAD, TTS, GPU, an LLM, or auth/OTP. Later phases.
- The Sarvam call may be out of date — match it to CURRENT Sarvam docs the user provides,
  or fix from the real error. If WebM audio is rejected, add an ffmpeg convert to WAV.

## What you should do
- Set up the Python venv and dependencies.
- Run backend (uvicorn 8000) + serve frontend (8080) locally first; help deploy to EC2.
- Fix errors the user pastes back; iterate.

## What the user must do (you cannot)
- Create the RDS Postgres instance; build DATABASE_URL; run the table SQL (README).
- Create the PRIVATE S3 bucket + IAM policy/role scoped to just that bucket.
- Launch EC2, attach the role, open ports; allow EC2 -> RDS on 5432.
- Get the Sarvam API key.
Give a clear manual-steps checklist and wait for the values.

## Honesty
No real auth this phase — identity is self-reported. Audio goes to Sarvam (third party).
Full privacy + real auth are later phases. Consent text must say audio is recorded/reviewed.
