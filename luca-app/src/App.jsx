import React, { useState, useRef, useEffect } from 'react';
import Starfield from './components/Starfield';
import LoginPage from './components/LoginPage';
import { PWABadge } from './components/PWABadge';
import './index.css';
import './App.css';

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'http://127.0.0.1:8000';

// ── Liquid capsule constants ───────────────────────────────────────────────
const CAPSULE_WIDTH = 110;
const CAPSULE_HEIGHT = 48;

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function createLiquidState() {
  return {
    level: 0,
    levelVelocity: 0,
    glow: 0,
    glowVelocity: 0,
    holdUntil: 0,
    flow: 0,
    drift: 0,
    lastTime: 0,
    blobs: [
      { offset: 0.08, speed: 0.62, depth: 0.26, size: 0.9,  phase: 0.2 },
      { offset: 0.33, speed: 0.44, depth: 0.44, size: 1.1,  phase: 1.4 },
      { offset: 0.56, speed: 0.71, depth: 0.58, size: 0.85, phase: 2.4 },
      { offset: 0.78, speed: 0.53, depth: 0.37, size: 1.0,  phase: 3.1 },
    ],
  };
}

function stepSpring(state, key, velocityKey, target, tension, damping, dt) {
  const force = (target - state[key]) * tension;
  state[velocityKey] += force * dt;
  state[velocityKey] *= Math.exp(-damping * dt);
  state[key] += state[velocityKey] * dt;
}

function resizeCapsuleCanvas(canvas) {
  const ratio = window.devicePixelRatio || 1;
  if (
    canvas.width  !== Math.round(CAPSULE_WIDTH  * ratio) ||
    canvas.height !== Math.round(CAPSULE_HEIGHT * ratio)
  ) {
    canvas.width  = Math.round(CAPSULE_WIDTH  * ratio);
    canvas.height = Math.round(CAPSULE_HEIGHT * ratio);
  }
  return ratio;
}

function drawRoundedPath(ctx, width, height, radius) {
  ctx.beginPath();
  ctx.moveTo(radius, 0);
  ctx.arcTo(width, 0,      width, height, radius);
  ctx.arcTo(width, height, 0,     height, radius);
  ctx.arcTo(0,     height, 0,     0,      radius);
  ctx.arcTo(0,     0,      width, 0,      radius);
  ctx.closePath();
}

function drawLiquidCapsule(canvas, state) {
  if (!canvas) return;

  const ratio  = resizeCapsuleCanvas(canvas);
  const ctx    = canvas.getContext('2d');
  const width  = CAPSULE_WIDTH;
  const height = CAPSULE_HEIGHT;
  const radius = height / 2;
  const glow   = clamp(state.glow, 0, 1);
  const phase  = state.flow;
  const drift  = state.drift;

  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.scale(ratio, ratio);

  ctx.save();
  drawRoundedPath(ctx, width, height, radius);
  ctx.clip();

  const backdrop = ctx.createLinearGradient(0, 0, 0, height);
  backdrop.addColorStop(0, 'rgba(4, 6, 12, 1)');
  backdrop.addColorStop(1, 'rgba(0, 0, 0, 1)');
  ctx.fillStyle = backdrop;
  ctx.fillRect(0, 0, width, height);

  ctx.save();
  ctx.globalCompositeOperation = 'screen';
  ctx.filter = `blur(${8 + glow * 6}px)`;

  const drawAuroraBlob = (cx, cy, rx, ry, r, g, b, alpha) => {
    ctx.beginPath();
    const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.max(rx, ry));
    grad.addColorStop(0, `rgba(${r}, ${g}, ${b}, ${alpha})`);
    grad.addColorStop(1, `rgba(${r}, ${g}, ${b}, 0)`);
    ctx.fillStyle = grad;
    ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
    ctx.fill();
  };

  // Base idle glow
  const idleAlpha = 0.15 + glow * 0.4;
  drawAuroraBlob(width * 0.5, height * 0.9, width * 0.6, height * 0.5, 60, 100, 255, idleAlpha);

  const activeAlpha = 0.05 + glow * 0.65;

  // Blob 1: Purple/Indigo
  const cx1 = width * 0.3 + Math.sin(phase * 1.2) * width * 0.2;
  const cy1 = height * 0.9 - glow * height * 0.5 + Math.cos(drift * 1.5) * 3;
  drawAuroraBlob(cx1, cy1, width * 0.4 + glow * width * 0.2, height * 0.3 + glow * height * 0.4, 140, 60, 255, activeAlpha);

  // Blob 2: Cyan/Light Blue
  const cx2 = width * 0.7 + Math.sin(phase * 0.9 + 2) * width * 0.2;
  const cy2 = height * 0.9 - glow * height * 0.6 + Math.cos(drift * 1.1 + 1) * 3;
  drawAuroraBlob(cx2, cy2, width * 0.35 + glow * width * 0.3, height * 0.25 + glow * height * 0.5, 80, 180, 255, activeAlpha * 0.8);

  // Blob 3: Deep Blue center
  const cx3 = width * 0.5 + Math.sin(phase * 1.5 + 4) * width * 0.1;
  const cy3 = height * 0.95 - glow * height * 0.4;
  drawAuroraBlob(cx3, cy3, width * 0.5 + glow * width * 0.2, height * 0.3 + glow * height * 0.3, 40, 80, 255, activeAlpha);

  ctx.restore();
  ctx.restore();
}

// ── Component ─────────────────────────────────────────────────────────────
function App() {
  // Auth
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [user, setUser] = useState(null);

  // App state
  const [isChatMode, setIsChatMode]   = useState(false);
  const [isVoiceMode, setIsVoiceMode] = useState(false);
  const [isLoading, setIsLoading]     = useState(false);
  const [messages, setMessages]       = useState([]);
  const [transcript, setTranscript]   = useState('');

  // TTS state
  const [audioCache,  setAudioCache]  = useState({});
  const [ttsLoading,  setTtsLoading]  = useState({});
  const [ttsDisabled, setTtsDisabled] = useState(false);

  // Refs
  const wasSecondaryRef    = useRef(false);
  const messagesEndRef     = useRef(null);
  const buttonRef          = useRef(null);
  const canvasRef          = useRef(null);
  const audioCtxRef        = useRef(null);
  const animationFrameRef  = useRef(null);
  const liquidStateRef     = useRef(createLiquidState());
  const mediaRecorderRef   = useRef(null);
  const chunksRef          = useRef([]);
  const micStreamRef       = useRef(null);
  const currentAudioRef    = useRef(null);

  // ── Restore session from localStorage ──────────────────────────────────
  useEffect(() => {
    const stored = localStorage.getItem('lucaUser');
    if (stored) {
      try {
        const parsed = JSON.parse(stored);
        // Require backend userId — old sessions without it must re-login
        if (parsed.fullName && parsed.mobileNumber && parsed.userId) {
          setUser(parsed);
          setIsLoggedIn(true);
        }
      } catch {
        console.error('Invalid session data in localStorage');
      }
    }
  }, []);

  const handleLogin = (userData) => {
    setUser(userData);
    setIsLoggedIn(true);
  };

  const handleLogout = () => {
    localStorage.removeItem('lucaUser');
    localStorage.removeItem('vc_user_id');
    localStorage.removeItem('vc_identifier');
    localStorage.removeItem('vc_name');
    setUser(null);
    setIsLoggedIn(false);
    setIsChatMode(false);
    setIsVoiceMode(false);
    setMessages([]);
    setTranscript('');
  };

  // ── Voice mode: record + visualise ──────────────────────────────────────
  useEffect(() => {
    let streamRef;

    if (isVoiceMode) {
      setTranscript('');

      navigator.mediaDevices.getUserMedia({ audio: true })
        .then(stream => {
          streamRef = stream;
          micStreamRef.current = stream;

          // Start MediaRecorder
          const recorder = new MediaRecorder(stream);
          chunksRef.current = [];
          recorder.ondataavailable = e => { if (e.data.size > 0) chunksRef.current.push(e.data); };
          mediaRecorderRef.current = recorder;
          recorder.start();

          // Liquid capsule visualization (unchanged from original)
          const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
          audioCtxRef.current = audioCtx;
          const analyser = audioCtx.createAnalyser();
          analyser.fftSize = 1024;
          analyser.smoothingTimeConstant = 0.08;
          audioCtx.createMediaStreamSource(stream).connect(analyser);
          const frequencyData  = new Uint8Array(analyser.frequencyBinCount);
          const liquidState    = liquidStateRef.current;
          liquidState.lastTime = 0;

          const renderFrame = () => {
            const now = performance.now();
            const dt  = liquidState.lastTime
              ? Math.min((now - liquidState.lastTime) / 1000, 0.04)
              : 1 / 60;
            liquidState.lastTime = now;

            analyser.getByteFrequencyData(frequencyData);

            let sum = 0;
            const voiceBins = 100;
            for (let i = 0; i < voiceBins; i++) sum += frequencyData[i];
            const rawVolume = Math.min((sum / voiceBins) / 40, 1);

            liquidState.level += (rawVolume - liquidState.level) * 0.03;
            liquidState.glow   = Math.min(liquidState.level * 1.2, 1);
            liquidState.flow  += dt * (0.01 + liquidState.level * 0.6);
            liquidState.drift += dt * (0.005 + liquidState.glow * 0.5);

            if (buttonRef.current) {
              buttonRef.current.style.boxShadow =
                `0 0 ${14 + liquidState.glow * 20}px rgba(71, 118, 255, ${0.08 + liquidState.glow * 0.22}), 0 10px 24px rgba(0, 0, 0, 0.45)`;
            }

            drawLiquidCapsule(canvasRef.current, liquidState);
            animationFrameRef.current = requestAnimationFrame(renderFrame);
          };

          drawLiquidCapsule(canvasRef.current, liquidState);
          renderFrame();
        })
        .catch(err => console.error('Mic access denied', err));
    }

    return () => {
      if (animationFrameRef.current) cancelAnimationFrame(animationFrameRef.current);
      liquidStateRef.current = createLiquidState();
      drawLiquidCapsule(canvasRef.current, liquidStateRef.current);
      if (audioCtxRef.current && audioCtxRef.current.state !== 'closed') audioCtxRef.current.close();
      if (streamRef) streamRef.getTracks().forEach(t => t.stop());
      if (micStreamRef.current === streamRef) micStreamRef.current = null;
    };
  }, [isVoiceMode]);

  // ── Scroll chat to bottom ────────────────────────────────────────────────
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Draw initial idle capsule once
  useEffect(() => {
    drawLiquidCapsule(canvasRef.current, liquidStateRef.current);
  }, []);

  // ── Browser back-button management ──────────────────────────────────────
  useEffect(() => {
    const isSecondary = isChatMode || isVoiceMode;
    if (isSecondary && !wasSecondaryRef.current) {
      window.history.pushState({ page: 'secondary' }, '');
    }
    wasSecondaryRef.current = isSecondary;
  }, [isChatMode, isVoiceMode]);

  useEffect(() => {
    const handlePopState = () => {
      if (isChatMode || isVoiceMode) {
        _stopRecorder();
        setIsChatMode(false);
        setIsVoiceMode(false);
        setTranscript('');
      }
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, [isChatMode, isVoiceMode]);

  // ── Helpers ──────────────────────────────────────────────────────────────
  const _stopRecorder = () => {
    const rec = mediaRecorderRef.current;
    if (rec && rec.state !== 'inactive') rec.stop();
  };

  // ── Handlers ─────────────────────────────────────────────────────────────
  const handleOpenChat = () => setIsVoiceMode(true);

  const handleVoiceCancel = () => {
    _stopRecorder();
    setIsVoiceMode(false);
    setTranscript('');
  };

  const handleVoiceSuccess = () => {
    const recorder = mediaRecorderRef.current;
    const doSubmit = () => {
      // Stop mic stream now that we have all chunks
      if (micStreamRef.current) {
        micStreamRef.current.getTracks().forEach(t => t.stop());
        micStreamRef.current = null;
      }
      const blob = new Blob(chunksRef.current, { type: 'audio/webm' });
      setIsVoiceMode(false);
      setIsLoading(true);
      setIsChatMode(true);
      setMessages([]);
      setAudioCache({});
      setTtsLoading({});
      _callBackend(blob);
    };

    if (recorder && recorder.state !== 'inactive') {
      recorder.onstop = doSubmit;
      recorder.stop();
    } else {
      doSubmit();
    }
  };

  const handleBackButtonClick = () => {
    _stopRecorder();
    if (window.history.state?.page === 'secondary') {
      window.history.back();
    } else {
      setIsChatMode(false);
      setIsVoiceMode(false);
      setTranscript('');
    }
  };

  // ── Backend: transcribe → LLM → return JSON ────────────────────────────
  const _callBackend = async (blob) => {
    const userId = localStorage.getItem('vc_user_id');
    if (!userId) { handleLogout(); return; }

    const form = new FormData();
    form.append('audio', blob, 'clip.webm');
    form.append('user_id', userId);

    try {
      const res = await fetch(`${BACKEND_URL}/transcribe_stream`, { method: 'POST', body: form });

      if (!res.ok) {
        if (res.status === 401) { handleLogout(); return; }
        const data = await res.json().catch(() => ({}));
        setMessages([{ role: 'ai', content: 'Error: ' + (data.detail || res.status) }]);
        setIsLoading(false);
        return;
      }

      const data = await res.json();

      if (data.status === 'recorded_only') {
        setIsLoading(false);
        setIsChatMode(false);
        return;
      }

      setMessages([
        { role: 'user', content: data.transcript || '(empty transcript)' },
        { role: 'ai',   content: data.reply || 'Reply unavailable.', language: data.language },
      ]);
      setIsLoading(false);

    } catch {
      setMessages([{ role: 'ai', content: 'Could not reach the backend.' }]);
      setIsLoading(false);
    }
  };

  // ── On-demand TTS (click-to-play) ────────────────────────────────────────
  const _stopCurrentAudio = () => {
    if (currentAudioRef.current) {
      currentAudioRef.current.pause();
      currentAudioRef.current.currentTime = 0;
      currentAudioRef.current = null;
    }
  };

  const _playAudioUrl = (url) => {
    _stopCurrentAudio();
    const audioEl = new Audio(url);
    currentAudioRef.current = audioEl;
    audioEl.addEventListener('ended', () => {
      if (currentAudioRef.current === audioEl) currentAudioRef.current = null;
    });
    audioEl.play().catch(() => {});
  };

  const _playTTS = async (text, language, idx) => {
    if (audioCache[idx]) {
      _playAudioUrl(audioCache[idx]);
      return;
    }
    setTtsLoading(prev => ({ ...prev, [idx]: true }));
    try {
      const userId = localStorage.getItem('vc_user_id');
      const res = await fetch(`${BACKEND_URL}/tts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, user_id: userId, language }),
      });
      const ct = res.headers.get('Content-Type') || '';
      if (ct.includes('application/json')) {
        const data = await res.json();
        if (data.status === 'tts_disabled') { setTtsDisabled(true); return; }
        console.error('TTS error:', data.message || res.status);
        return;
      }
      if (!res.ok) { console.error('TTS request failed:', res.status); return; }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      setAudioCache(prev => ({ ...prev, [idx]: url }));
      _playAudioUrl(url);
    } catch (e) {
      console.error('TTS fetch error:', e);
    } finally {
      setTtsLoading(prev => ({ ...prev, [idx]: false }));
    }
  };

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <>
      <main className={`app-main ${isChatMode ? 'chat-mode' : 'fade-in'}`}>

        {/* Premium Background Layers */}
        <div className="ambient-background">
          <div className="ambient-colors"></div>
          <div className="ambient-texture"></div>
          <div className="ambient-valley-mask"></div>
        </div>

        {/* Starfield */}
        <Starfield isFullScreen={isChatMode || isVoiceMode} />


        {!isLoggedIn ? (
          <LoginPage onLogin={handleLogin} />
        ) : (
          <>
            {/* Back button (voice / chat modes) */}
            {(isChatMode || isVoiceMode) && (
              <button
                className="back-btn fade-in"
                onClick={handleBackButtonClick}
                aria-label="Go Back"
              >
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="15 18 9 12 15 6"></polyline>
                </svg>
              </button>
            )}

            {/* Sign-out — only on home / chat, not during recording */}
            {!isVoiceMode && (
              <button className="signout-btn" onClick={handleLogout}>
                Sign out
              </button>
            )}

            {/* Center content — home & voice mode */}
            {(!isChatMode || isVoiceMode) && (
              <div className="center-content">
                <h1 className="welcome-text fade-in-text">
                  {isVoiceMode ? (transcript || 'Listening...') : 'Welcome'}
                </h1>
              </div>
            )}

            {/* Chat history */}
            {isChatMode && !isVoiceMode && (
              <div className="chat-history">
                {isLoading && <div className="message ai">Processing…</div>}
                {messages.map((msg, idx) => (
                  <div key={idx} className={`message ${msg.role}`}>
                    <span>{msg.content}</span>
                    {msg.role === 'ai' && msg.content && (
                      <button
                        className={`tts-btn${ttsDisabled ? ' tts-btn--disabled' : ''}`}
                        onClick={() => !ttsDisabled && !ttsLoading[idx] && _playTTS(msg.content, msg.language, idx)}
                        disabled={ttsDisabled || !!ttsLoading[idx]}
                        aria-label="Play audio"
                      >
                        {ttsLoading[idx] ? (
                          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="tts-spinner">
                            <line x1="12" y1="2" x2="12" y2="6" /><line x1="12" y1="18" x2="12" y2="22" />
                            <line x1="4.93" y1="4.93" x2="7.76" y2="7.76" /><line x1="16.24" y1="16.24" x2="19.07" y2="19.07" />
                            <line x1="2" y1="12" x2="6" y2="12" /><line x1="18" y1="12" x2="22" y2="12" />
                            <line x1="4.93" y1="19.07" x2="7.76" y2="16.24" /><line x1="16.24" y1="7.76" x2="19.07" y2="4.93" />
                          </svg>
                        ) : (
                          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
                            <path d="M19.07 4.93a10 10 0 0 1 0 14.14" />
                            <path d="M15.54 8.46a5 5 0 0 1 0 7.07" />
                          </svg>
                        )}
                      </button>
                    )}
                  </div>
                ))}
                <div ref={messagesEndRef} />
              </div>
            )}

            {/* Ask LUCA search bar */}
            {!isVoiceMode && (
              <div className="bottom-bar-container slide-up">
                <div className="search-bar" onClick={handleOpenChat}>
                  <span className="placeholder-text">Ask LUCA</span>
                </div>
              </div>
            )}

            {/* Voice controls */}
            {isVoiceMode && (
              <div className="voice-container slide-up">
                <div className="voice-bottom-controls">
                  <button className="voice-btn" aria-label="Cancel" onClick={handleVoiceCancel}>
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <line x1="18" y1="6"  x2="6"  y2="18"></line>
                      <line x1="6"  y1="6"  x2="18" y2="18"></line>
                    </svg>
                  </button>

                  <div className="voice-glow-btn" ref={buttonRef}>
                    <canvas
                      ref={canvasRef}
                      className="liquid-canvas"
                      width={CAPSULE_WIDTH}
                      height={CAPSULE_HEIGHT}
                      aria-hidden="true"
                    />
                    <div className="voice-capsule-glass"></div>
                    <div className="voice-capsule-rim"></div>
                  </div>

                  <button className="voice-btn" aria-label="Done" onClick={handleVoiceSuccess}>
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="20 6 9 17 4 12"></polyline>
                    </svg>
                  </button>
                </div>
              </div>
            )}
          </>
        )}

      </main>

      <PWABadge />
    </>
  );
}

export default App;
