"""
Phase 1 backend — record / save / transcribe (no LLM, no streaming, no auth).

Identity (self-identification, NOT verified):
  - First time: name + phone/email  -> create a `users` row + generate user_id (uuid).
  - Returning : phone/email only     -> look up the existing user_id.
  - No password/OTP/token. Browser remembers the user_id. Trust-the-client (test only).

Usage limit:
  - DAILY_LIMIT (env) = max COMPLETED recordings per user per rolling 24h.
  - 0 (default for Phase 1) = unlimited. Set a real number later to switch it on.
  - When a user is over the limit, the request is blocked BEFORE any S3/ASR work,
    and a row is logged with status 'quota_exhausted'.

Stack: RDS Postgres (users + recordings) | S3 (audio, private) | Sarvam (ASR) | EC2.
The S3 folder is the uuid user_id, never the raw phone/email (keeps PII out of keys).
"""

import os
import uuid
import asyncio
import base64
import random
import time
from contextlib import asynccontextmanager

import boto3
import httpx
import psycopg
from pydantic import BaseModel
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
load_dotenv()

AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")
DATABASE_URL = os.environ["DATABASE_URL"]
S3_BUCKET = os.environ["S3_BUCKET"]
SARVAM_API_KEY = os.environ["SARVAM_API_KEY"]
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")
DAILY_LIMIT = int(os.environ.get("DAILY_LIMIT", "0"))   # 0 = unlimited (Phase 1 default)
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
LLM_ENDPOINT = os.environ.get("LLM_ENDPOINT", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "")
LLM_MODEL_VERSION = os.environ.get("LLM_MODEL_VERSION", "")
SARVAM_TTS_API_KEY = os.environ.get("SARVAM_TTS_API_KEY", "")
TTS_MODEL = os.environ.get("TTS_MODEL", "bulbul:v3")
TTS_SPEAKER = os.environ.get("TTS_SPEAKER", "shubh")
TTS_SAMPLE_RATE = int(os.environ.get("TTS_SAMPLE_RATE", "24000"))
ACTIVE_CLASS       = os.environ.get("ACTIVE_CLASS", "")  # class that gets full ASR/LLM/TTS; restart backend after changing in .env
GOOGLE_TTS_API_KEY = os.environ.get("GOOGLE_TTS_API_KEY", "")
TTS_ENABLED        = os.environ.get("TTS_ENABLED", "true")

SYSTEM_PROMPT = (
    "You are LUCA, made by 10x Technologies. LUCA stands for Language Understanding Companion Assistant. "
    "You are inside the 10x Technologies website and you help students learn properly. "
    "Act as a mentor, tutor, and guide. Give clear, correct, age-appropriate educational explanations. "
    "Adapt your response to the student's understanding level. "
    "If a topic is complex, break it down step by step. "
    "If a topic is small, explain it simply and precisely. "
    "Keep spoken replies concise and conversational, a few sentences at most, "
    "with no bullet points or symbols since your reply is read aloud."
)

_ALLOWED_LANGUAGES = {
    "en-IN", "hi-IN", "bn-IN", "ta-IN", "te-IN",
    "kn-IN", "ml-IN", "mr-IN", "gu-IN", "pa-IN", "od-IN",
}

# Chirp 3 HD preferred; verify at https://cloud.google.com/text-to-speech/docs/voices
_GOOGLE_VOICES: dict[str, tuple[str, str]] = {
    "en-IN": ("en-IN", "en-IN-Chirp3-HD-Aoede"),
    "hi-IN": ("hi-IN", "hi-IN-Chirp3-HD-Aoede"),
    "bn-IN": ("bn-IN", "bn-IN-Chirp3-HD-Aoede"),
    "ta-IN": ("ta-IN", "ta-IN-Chirp3-HD-Aoede"),
    "te-IN": ("te-IN", "te-IN-Chirp3-HD-Aoede"),
    "kn-IN": ("kn-IN", "kn-IN-Chirp3-HD-Aoede"),
    "ml-IN": ("ml-IN", "ml-IN-Chirp3-HD-Aoede"),
    "mr-IN": ("mr-IN", "mr-IN-Chirp3-HD-Aoede"),
    "gu-IN": ("gu-IN", "gu-IN-Chirp3-HD-Aoede"),
    "pa-IN": ("pa-IN", "pa-IN-Standard-A"),     # Chirp 3 HD not available; Standard fallback
    "od-IN": ("od-IN", "od-IN-Standard-A"),     # Chirp 3 HD not available; Standard fallback
}
_GOOGLE_VOICE_DEFAULT = ("en-IN", "en-IN-Chirp3-HD-Aoede")

s3 = boto3.client("s3", region_name=AWS_REGION)

_HTTP_LIMITS = httpx.Limits(max_connections=200, max_keepalive_connections=50)

_sarvam_client:     httpx.AsyncClient | None = None
_llm_client:        httpx.AsyncClient | None = None
_google_tts_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _sarvam_client, _llm_client, _google_tts_client
    _sarvam_client     = httpx.AsyncClient(limits=_HTTP_LIMITS, timeout=60.0)
    _llm_client        = httpx.AsyncClient(limits=_HTTP_LIMITS, timeout=60.0)
    _google_tts_client = httpx.AsyncClient(limits=_HTTP_LIMITS, timeout=30.0)
    await run_in_threadpool(_ensure_tts_usage_table)
    yield
    await _sarvam_client.aclose()
    await _llm_client.aclose()
    await _google_tts_client.aclose()


app = FastAPI(title="Voice Phase 1 (no auth)", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGIN] if ALLOWED_ORIGIN != "*" else ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Transcript", "X-Reply"],
)


# ---------- identity (lookup-or-create) ----------
class LoginIn(BaseModel):
    name: str | None = None
    identifier: str  # phone number OR email
    class_standard: str | None = None


def _normalize(identifier: str):
    s = identifier.strip()
    if "@" in s:
        return s.lower(), "email"
    return s.replace(" ", ""), "phone"


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def _login(name, identifier, id_type, ip_address, class_standard):
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("select user_id, name, approved from users where identifier = %s", (identifier,))
            row = cur.fetchone()
            if row:
                return str(row[0]), row[1], bool(row[2])   # existing user; name NOT overwritten
            cur.execute(
                "insert into users (name, identifier, id_type, ip_address, class_standard, approved)"
                " values (%s, %s, %s, %s, %s, true) returning user_id, name, approved",
                (name, identifier, id_type, ip_address, class_standard),
            )
            new = cur.fetchone()
        conn.commit()
        return str(new[0]), new[1], bool(new[2])


def _get_user_class(user_id) -> str | None:
    """Returns class_standard if user exists, None if not found."""
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("select class_standard from users where user_id = %s", (user_id,))
            row = cur.fetchone()
            return row[0] if row else None


def _user_exists(user_id) -> bool:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("select 1 from users where user_id = %s", (user_id,))
            return cur.fetchone() is not None


def _count_recent_completed(user_id) -> int:
    """How many COMPLETED recordings this user made in the last 24h."""
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """select count(*) from recordings
                   where user_id = %s and status = 'completed'
                     and created_at > now() - interval '1 day'""",
                (user_id,),
            )
            return cur.fetchone()[0]


@app.post("/login")
async def login(body: LoginIn, request: Request):
    identifier, id_type = _normalize(body.identifier)
    if not identifier:
        raise HTTPException(status_code=400, detail="Enter a phone number or email")
    name = (body.name or "").strip() or None
    class_standard = (body.class_standard or "").strip() or None
    ip = _client_ip(request)
    user_id, stored_name, approved = await run_in_threadpool(
        _login, name, identifier, id_type, ip, class_standard
    )
    return {"user_id": user_id, "name": stored_name, "identifier": identifier, "approved": approved}


# ---------- storage / asr / db ----------
def _s3_put(key, body, content_type):
    s3.put_object(Bucket=S3_BUCKET, Key=key, Body=body, ContentType=content_type)


async def upload_audio(audio_bytes, key, content_type):
    try:
        await run_in_threadpool(_s3_put, key, audio_bytes, content_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"S3 upload failed: {e}")


_BACKOFF = (0.5, 1.0, 2.0)  # retry delays (seconds) for attempts 1, 2, 3


async def _sarvam_post(label: str, url: str, **kwargs) -> httpx.Response:
    """POST to Sarvam with up to 3 retries on 429 or transient network errors."""
    last_exc: Exception | None = None
    r: httpx.Response | None = None
    for attempt in range(len(_BACKOFF) + 1):  # initial attempt + 3 retries
        try:
            r = await _sarvam_client.post(url, **kwargs)
            last_exc = None
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            last_exc = exc
            if attempt < len(_BACKOFF):
                delay = _BACKOFF[attempt] + random.uniform(0, 0.1)
                print(f"{label} {type(exc).__name__}, retry {attempt + 1}/{len(_BACKOFF)} after {delay:.1f}s", flush=True)
                await asyncio.sleep(delay)
            continue
        if r.status_code != 429:
            return r
        if attempt < len(_BACKOFF):
            delay = _BACKOFF[attempt] + random.uniform(0, 0.1)
            print(f"{label} 429, retry {attempt + 1}/{len(_BACKOFF)} after {delay:.1f}s", flush=True)
            await asyncio.sleep(delay)
    if last_exc is not None:
        raise last_exc
    return r  # type: ignore[return-value]


async def transcribe(audio_bytes, filename, content_type):
    """
    Send audio to Sarvam -> (transcript_text, language_code).
    >>> VERIFY AGAINST CURRENT SARVAM DOCS <<<  This is the only ASR touch-point.
    """
    r = await _sarvam_post(
        "ASR",
        "https://api.sarvam.ai/speech-to-text",
        headers={"api-subscription-key": SARVAM_API_KEY},
        files={"file": (filename, audio_bytes, content_type)},
        data={"model": "saarika:v2.5", "language_code": "unknown"},
        timeout=60,
    )
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"ASR failed: {r.text}")
    body = r.json()
    return body.get("transcript", ""), body.get("language_code")


async def generate_reply(transcript_text: str, language) -> tuple[str, int]:
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": transcript_text},
        ],
        "max_tokens": 256,
        "temperature": 1.0,
        "top_p": 0.95,
        "top_k": 64,
    }
    r = await _llm_client.post(LLM_ENDPOINT, json=payload, timeout=30)
    r.raise_for_status()
    body = r.json()
    reply_text = body["choices"][0]["message"]["content"]
    total_tokens = body.get("usage", {}).get("total_tokens", 0)
    return reply_text, total_tokens


async def synthesize(reply_text: str, language: str | None) -> bytes:
    lang = language if language in _ALLOWED_LANGUAGES else "en-IN"
    payload = {
        "text": reply_text[:2500],
        "target_language_code": lang,
        "model": TTS_MODEL,
        "speaker": TTS_SPEAKER,
        "speech_sample_rate": TTS_SAMPLE_RATE,
        "output_audio_codec": "wav",
    }
    r = await _sarvam_post(
        "TTS",
        "https://api.sarvam.ai/text-to-speech",
        headers={
            "api-subscription-key": SARVAM_TTS_API_KEY,
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    if r.status_code != 200:
        raise RuntimeError(f"TTS failed ({r.status_code}): {r.text}")
    audios = r.json().get("audios", [])
    if not audios:
        raise RuntimeError("TTS response missing audios field")
    return base64.b64decode(audios[0])


def _db_insert(user_id, audio_key, text, language, status,
               llm_response_text=None, tokens_used=None, model_version=None):
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """insert into recordings
                     (user_id, audio_key, transcript_text, language, status,
                      llm_response_text, tokens_used, model_version)
                   values (%s, %s, %s, %s, %s, %s, %s, %s) returning id""",
                (user_id, audio_key, text, language, status,
                 llm_response_text, tokens_used, model_version),
            )
            new_id = cur.fetchone()[0]
        conn.commit()
    return new_id


async def save_recording(user_id, audio_key, text, language, status,
                         llm_response_text=None, tokens_used=None, model_version=None):
    try:
        return await run_in_threadpool(_db_insert, user_id, audio_key, text, language, status,
                                       llm_response_text, tokens_used, model_version)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB insert failed: {e}")


def _ensure_tts_usage_table():
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tts_usage (
                    id         SERIAL PRIMARY KEY,
                    user_id    UUID NOT NULL REFERENCES users(user_id),
                    language   TEXT,
                    char_count INTEGER NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
        conn.commit()


def _insert_tts_usage(user_id, language, char_count):
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tts_usage (user_id, language, char_count) VALUES (%s, %s, %s)",
                (user_id, language, char_count),
            )
        conn.commit()


def _get_tts_usage():
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COALESCE(SUM(char_count), 0) FROM tts_usage")
            total = cur.fetchone()[0]
            cur.execute("""
                SELECT u.name, u.identifier, t.language,
                       SUM(t.char_count) AS chars, COUNT(*) AS calls
                FROM tts_usage t
                JOIN users u ON u.user_id = t.user_id
                GROUP BY u.user_id, u.name, u.identifier, t.language
                ORDER BY chars DESC
            """)
            rows = cur.fetchall()
        return {
            "total_chars": int(total),
            "per_user_language": [
                {"name": r[0], "identifier": r[1], "language": r[2],
                 "char_count": r[3], "calls": r[4]}
                for r in rows
            ],
        }


@app.get("/healthz")
async def healthz():
    return {"ok": True, "daily_limit": DAILY_LIMIT}


@app.post("/transcribe")
async def transcribe_endpoint(audio: UploadFile = File(...), user_id: str = Form(...)):
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Bad user_id")
    if not await run_in_threadpool(_user_exists, uid):
        raise HTTPException(status_code=401, detail="Unknown user — sign in again")

    audio_bytes = await audio.read()
    content_type = audio.content_type or "audio/webm"
    ext = (audio.filename or "clip.webm").split(".")[-1]
    audio_key = f"{uid}/{uuid.uuid4()}.{ext}"

    # Save audio to S3 FIRST so the recording survives even if ASR fails or quota is hit.
    await upload_audio(audio_bytes, audio_key, content_type)

    # --- usage limit: audio already saved; skip ASR and return a soft 200 ---
    if DAILY_LIMIT > 0:
        used = await run_in_threadpool(_count_recent_completed, uid)
        if used >= DAILY_LIMIT:
            await save_recording(uid, audio_key, "", None, "quota_exhausted")
            return {
                "transcript": "",
                "status": "quota_exhausted",
                "warning": "Daily limit reached — your audio is saved but not transcribed.",
            }

    t_asr = t_llm = t_tts = 0.0

    _t = time.perf_counter()
    try:
        text, language = await transcribe(audio_bytes, audio.filename or "clip.webm", content_type)
        t_asr = time.perf_counter() - _t
    except HTTPException:
        await save_recording(uid, audio_key, "", None, "error")
        raise

    reply_text = ""
    tokens_used = 0
    final_status = "completed"
    _t = time.perf_counter()
    try:
        reply_text, tokens_used = await generate_reply(text, language)
    except Exception:
        final_status = "llm_failed"
    t_llm = time.perf_counter() - _t

    reply_audio_b64 = None
    if final_status == "completed" and reply_text:
        _t = time.perf_counter()
        try:
            wav_bytes = await synthesize(reply_text, language)
            reply_audio_b64 = base64.b64encode(wav_bytes).decode()
        except Exception:
            final_status = "tts_failed"
        t_tts = time.perf_counter() - _t

    print(
        f"ASR={t_asr:.2f}s LLM={t_llm:.2f}s TTS={t_tts:.2f}s"
        f" total={t_asr + t_llm + t_tts:.2f}s status={final_status}",
        flush=True,
    )

    new_id = await save_recording(
        uid, audio_key, text, language, final_status,
        llm_response_text=reply_text or None,
        tokens_used=tokens_used or None,
        model_version=LLM_MODEL_VERSION,
    )
    resp = {"transcript": text, "language": language, "recording_id": str(new_id), "status": final_status}
    if reply_text:
        resp["reply"] = reply_text
    if reply_audio_b64:
        resp["reply_audio_b64"] = reply_audio_b64
    return resp


@app.post("/transcribe_stream")
async def transcribe_stream_endpoint(audio: UploadFile = File(...), user_id: str = Form(...)):
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Bad user_id")

    class_standard = await run_in_threadpool(_get_user_class, uid)
    if class_standard is None:
        raise HTTPException(status_code=401, detail="Unknown user — sign in again")

    audio_bytes = await audio.read()
    content_type = audio.content_type or "audio/webm"
    ext = (audio.filename or "clip.webm").split(".")[-1]
    audio_key = f"{uid}/{uuid.uuid4()}.{ext}"

    await upload_audio(audio_bytes, audio_key, content_type)

    if DAILY_LIMIT > 0:
        used = await run_in_threadpool(_count_recent_completed, uid)
        if used >= DAILY_LIMIT:
            await save_recording(uid, audio_key, "", None, "quota_exhausted")
            raise HTTPException(
                status_code=429,
                detail="Daily limit reached — recording saved but not processed.",
            )

    # PATH B: class not active — save audio, skip ASR/LLM/TTS
    if class_standard != ACTIVE_CLASS and class_standard != "Staff":
        try:
            await save_recording(uid, audio_key, "", None, "incomplete")
        except Exception as exc:
            print(f"PATH B DB save failed (audio is on S3): {exc}", flush=True)
        return JSONResponse({"status": "recorded_only"})

    # PATH A: active class or Staff — ASR → LLM → return JSON (TTS on-demand via /tts)
    try:
        text, language = await transcribe(audio_bytes, audio.filename or "clip.webm", content_type)
    except HTTPException:
        await save_recording(uid, audio_key, "", None, "error")
        raise

    reply_text = ""
    try:
        llm_payload = {
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            "max_tokens": 120,
            "temperature": 1.0,
            "top_p": 0.95,
            "top_k": 64,
        }
        llm_r = await _llm_client.post(LLM_ENDPOINT, json=llm_payload, timeout=30)
        llm_r.raise_for_status()
        reply_text = llm_r.json()["choices"][0]["message"]["content"]
    except Exception as exc:
        print(f"LLM error in transcribe_stream: {exc}", flush=True)
        await save_recording(uid, audio_key, text, language, "llm_failed")
        raise HTTPException(status_code=502, detail="LLM call failed")

    await save_recording(
        uid, audio_key, text, language, "completed",
        llm_response_text=reply_text, model_version=LLM_MODEL_VERSION,
    )
    return JSONResponse({
        "transcript": text,
        "language": language or "en-IN",
        "reply": reply_text,
    })


class TTSIn(BaseModel):
    text: str
    user_id: str
    language: str | None = None


@app.post("/tts")
async def tts_endpoint(body: TTSIn):
    if TTS_ENABLED.lower() != "true":
        return JSONResponse({"status": "tts_disabled", "message": "Audio is currently unavailable."})
    if not GOOGLE_TTS_API_KEY:
        return JSONResponse({"status": "tts_disabled", "message": "TTS not configured."})

    try:
        uid = uuid.UUID(body.user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Bad user_id")

    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    lang_code, voice_name = _GOOGLE_VOICES.get(body.language or "", _GOOGLE_VOICE_DEFAULT)

    google_payload = {
        "input": {"text": text},
        "voice": {"languageCode": lang_code, "name": voice_name},
        "audioConfig": {"audioEncoding": "MP3"},
    }

    try:
        r = await _google_tts_client.post(
            f"https://texttospeech.googleapis.com/v1/text:synthesize?key={GOOGLE_TTS_API_KEY}",
            json=google_payload,
            timeout=30,
        )
        if r.status_code != 200:
            raise RuntimeError(f"Google TTS returned {r.status_code}: {r.text[:200]}")
        audio_b64 = r.json().get("audioContent", "")
        if not audio_b64:
            raise RuntimeError("Google TTS returned no audioContent")
        mp3_bytes = base64.b64decode(audio_b64)
    except Exception as exc:
        print(f"Google TTS error: {exc}", flush=True)
        return JSONResponse({"status": "tts_error", "message": str(exc)}, status_code=502)

    try:
        await run_in_threadpool(_insert_tts_usage, uid, lang_code, len(text))
    except Exception as exc:
        print(f"TTS usage insert failed: {exc}", flush=True)

    return Response(content=mp3_bytes, media_type="audio/mpeg")


@app.get("/tts/usage")
async def tts_usage_endpoint(x_admin_token: str = Header(...)):
    if not ADMIN_TOKEN or x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid admin token")
    return await run_in_threadpool(_get_tts_usage)


