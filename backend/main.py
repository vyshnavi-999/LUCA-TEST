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
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from urllib.parse import quote
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

_ALLOWED_LANGUAGES = {
    "en-IN", "hi-IN", "bn-IN", "ta-IN", "te-IN",
    "kn-IN", "ml-IN", "mr-IN", "gu-IN", "pa-IN", "od-IN",
}

s3 = boto3.client("s3", region_name=AWS_REGION)

_HTTP_LIMITS = httpx.Limits(max_connections=200, max_keepalive_connections=50)

_sarvam_client: httpx.AsyncClient | None = None
_llm_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _sarvam_client, _llm_client
    _sarvam_client = httpx.AsyncClient(limits=_HTTP_LIMITS, timeout=60.0)
    _llm_client = httpx.AsyncClient(limits=_HTTP_LIMITS, timeout=60.0)
    yield
    await _sarvam_client.aclose()
    await _llm_client.aclose()


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
                "insert into users (name, identifier, id_type, ip_address, class_standard)"
                " values (%s, %s, %s, %s, %s) returning user_id, name, approved",
                (name, identifier, id_type, ip_address, class_standard),
            )
            new = cur.fetchone()
        conn.commit()
        return str(new[0]), new[1], bool(new[2])


def _user_approved(user_id) -> bool:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("select approved from users where user_id = %s", (user_id,))
            row = cur.fetchone()
            return bool(row[0]) if row else False


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
            {"role": "system", "content": "You are a helpful assistant. Reply concisely in the same language as the user."},
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
    if not await run_in_threadpool(_user_approved, uid):
        raise HTTPException(status_code=403, detail="Not approved yet")

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


# ---------- streaming TTS reply (binary MP3 forwarded directly to browser) ----------

_TTS_STREAM_URL = "https://api.sarvam.ai/text-to-speech/stream"

# Language-appropriate speakers for bulbul:v3 (per Sarvam recommendations).
_LANG_SPEAKER: dict[str, str] = {
    "en-IN": "neha",
    "hi-IN": "ritu",
    "bn-IN": "roopa",
    "ta-IN": "kavitha",
    "te-IN": "shruti",
    "kn-IN": "shubh",
    "ml-IN": "shubh",
    "mr-IN": "priya",
    "gu-IN": "manan",
    "pa-IN": "shubh",
    "od-IN": "shubh",
}


async def _open_tts_stream(payload: dict) -> httpx.Response:
    """
    POST to the Sarvam HTTP streaming TTS endpoint with 429/network retry.
    Returns an open streaming response — caller MUST close it (via aclose or full read).
    """
    last_exc: Exception | None = None
    r: httpx.Response | None = None
    for attempt in range(len(_BACKOFF) + 1):
        if r is not None:
            await r.aclose()
            r = None
        try:
            req = _sarvam_client.build_request(
                "POST", _TTS_STREAM_URL,
                headers={
                    "api-subscription-key": SARVAM_TTS_API_KEY,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            r = await _sarvam_client.send(req, stream=True)
            last_exc = None
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            last_exc = exc
            if attempt < len(_BACKOFF):
                delay = _BACKOFF[attempt] + random.uniform(0, 0.1)
                print(f"TTS stream {type(exc).__name__}, retry {attempt + 1}/{len(_BACKOFF)} in {delay:.1f}s", flush=True)
                await asyncio.sleep(delay)
            continue
        if r.status_code != 429:
            return r
        if attempt < len(_BACKOFF):
            delay = _BACKOFF[attempt] + random.uniform(0, 0.1)
            print(f"TTS stream 429, retry {attempt + 1}/{len(_BACKOFF)} in {delay:.1f}s", flush=True)
            await asyncio.sleep(delay)
    if last_exc is not None:
        raise last_exc
    return r  # type: ignore[return-value]


@app.post("/transcribe_stream")
async def transcribe_stream_endpoint(audio: UploadFile = File(...), user_id: str = Form(...)):
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Bad user_id")
    if not await run_in_threadpool(_user_exists, uid):
        raise HTTPException(status_code=401, detail="Unknown user — sign in again")
    if not await run_in_threadpool(_user_approved, uid):
        raise HTTPException(status_code=403, detail="Not approved yet")

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

    try:
        text, language = await transcribe(audio_bytes, audio.filename or "clip.webm", content_type)
    except HTTPException:
        await save_recording(uid, audio_key, "", None, "error")
        raise

    # Non-streaming LLM call — short reply suitable for TTS.
    reply_text = ""
    try:
        llm_payload = {
            "model": LLM_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a helpful voice assistant. "
                        "Reply in 1-2 short sentences in the same language as the user."
                    ),
                },
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

    lang = language if language in _ALLOWED_LANGUAGES else "en-IN"
    speaker = _LANG_SPEAKER.get(lang, TTS_SPEAKER)
    tts_payload = {
        "text": reply_text[:2500],
        "model": "bulbul:v3",
        "target_language_code": lang,
        "speaker": speaker,
        "output_audio_codec": "mp3",
        "pace": 1.0,
        "temperature": 0.6,
    }

    tts_r = await _open_tts_stream(tts_payload)

    if tts_r.status_code != 200:
        error_body = await tts_r.aread()
        await tts_r.aclose()
        print(f"TTS stream non-200 ({tts_r.status_code}): {error_body[:300]}", flush=True)
        await save_recording(
            uid, audio_key, text, language, "tts_failed",
            llm_response_text=reply_text, tokens_used=None, model_version=LLM_MODEL_VERSION,
        )
        return JSONResponse({
            "transcript": text,
            "language": language,
            "reply": reply_text,
            "status": "tts_failed",
        })

    # Stream binary MP3 chunks to the browser; save DB row in finally.
    async def _audio_gen():
        try:
            async for chunk in tts_r.aiter_bytes(4096):
                yield chunk
        finally:
            await tts_r.aclose()
            try:
                await run_in_threadpool(
                    _db_insert, uid, audio_key, text, language, "completed",
                    reply_text, None, LLM_MODEL_VERSION,
                )
            except Exception as exc:
                print(f"DB save error after TTS stream: {exc}", flush=True)

    return StreamingResponse(
        _audio_gen(),
        media_type="audio/mpeg",
        headers={
            "X-Transcript": quote(text),
            "X-Reply": quote(reply_text),
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )



# ---------- admin ----------
def _check_admin(token: str):
    if not ADMIN_TOKEN or token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid admin token")


def _get_pending_users():
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """select u.user_id, u.name, u.identifier, u.created_at, u.ip_address,
                          case when u.ip_address is not null
                               then (select count(*) from users u2
                                     where u2.ip_address = u.ip_address)
                               else 1
                          end as ip_count
                   from users u
                   where u.approved = false
                   order by u.created_at"""
            )
            return [
                {"user_id": str(r[0]), "name": r[1], "identifier": r[2],
                 "created_at": r[3].isoformat(), "ip_address": r[4], "ip_count": r[5]}
                for r in cur.fetchall()
            ]


def _approve_user(user_id):
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("update users set approved = true where user_id = %s", (user_id,))
        conn.commit()


class ApproveIn(BaseModel):
    user_id: str


@app.get("/admin/pending")
async def admin_pending(x_admin_token: str = Header(...)):
    _check_admin(x_admin_token)
    return await run_in_threadpool(_get_pending_users)


@app.post("/admin/approve")
async def admin_approve(body: ApproveIn, x_admin_token: str = Header(...)):
    _check_admin(x_admin_token)
    try:
        uid = uuid.UUID(body.user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Bad user_id")
    await run_in_threadpool(_approve_user, uid)
    return {"ok": True, "user_id": str(uid)}

