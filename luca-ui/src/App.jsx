import React, { useState, useRef, useEffect } from 'react';
import Starfield from './components/Starfield';
import { PWABadge } from './components/PWABadge';
import './index.css';
import './App.css';

function App() {
  const [isChatMode, setIsChatMode] = useState(false);
  const [isVoiceMode, setIsVoiceMode] = useState(false);
  const [messages, setMessages] = useState([]);
  const [transcript, setTranscript] = useState('');
  
  const messagesEndRef = useRef(null);
  const recognitionRef = useRef(null);
  const buttonRef = useRef(null);
  const audioCtxRef = useRef(null);
  const animationFrameRef = useRef(null);

  // Initialize Speech Recognition
  useEffect(() => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition) {
      const recognition = new SpeechRecognition();
      recognition.continuous = true;
      recognition.interimResults = true;
      
      recognition.onresult = (event) => {
        let currentTranscript = '';
        for (let i = 0; i < event.results.length; i++) {
          currentTranscript += event.results[i][0].transcript;
        }
        setTranscript(currentTranscript);
      };

      recognition.onerror = (event) => {
        console.error('Speech recognition error', event.error);
      };

      recognitionRef.current = recognition;
    }
  }, []);

  // Handle start/stop of listening and Audio Visualization
  useEffect(() => {
    let streamRef;
    if (isVoiceMode && recognitionRef.current) {
      setTranscript('');
      try {
        recognitionRef.current.start();
      } catch (e) {
        console.log('Recognition already started');
      }

      // Audio Visualization
      navigator.mediaDevices.getUserMedia({ audio: true })
        .then(stream => {
          streamRef = stream;
          const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
          audioCtxRef.current = audioCtx;
          const analyser = audioCtx.createAnalyser();
          analyser.fftSize = 256;
          const source = audioCtx.createMediaStreamSource(stream);
          source.connect(analyser);
          const dataArray = new Uint8Array(analyser.frequencyBinCount);

          const renderFrame = () => {
            analyser.getByteFrequencyData(dataArray);
            let sum = 0;
            for (let i = 0; i < dataArray.length; i++) {
              sum += dataArray[i];
            }
            const average = sum / dataArray.length;
            const volume = Math.min(average / 100, 1);

            if (buttonRef.current) {
              const time = Date.now() / 1000;
              const idleSine = (Math.sin(time * 2.5) + 1) / 2; // 0 to 1
              
              const scale = Math.max(1 + (idleSine * 0.05), 1 + (volume * 0.15));
              const opacity = Math.max(0.3 + (idleSine * 0.2), 0.3 + (volume * 0.7));
              const spread = Math.max(20 + (idleSine * 10), 20 + (volume * 50));
              
              buttonRef.current.style.transform = `scale(${scale})`;
              buttonRef.current.style.boxShadow = `inset 0 -10px ${20 + volume*20}px rgba(81, 45, 168, ${0.4 + volume*0.4}), 0 0 ${spread}px rgba(63, 81, 181, ${0.4 + volume*0.5})`;
              buttonRef.current.style.setProperty('--volume-opacity', opacity);
            }
            animationFrameRef.current = requestAnimationFrame(renderFrame);
          };
          renderFrame();
        })
        .catch(err => console.error('Mic access denied for viz', err));

    } else if (!isVoiceMode && recognitionRef.current) {
      recognitionRef.current.stop();
    }

    return () => {
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
      }
      if (audioCtxRef.current && audioCtxRef.current.state !== 'closed') {
        audioCtxRef.current.close();
      }
      if (streamRef) {
        streamRef.getTracks().forEach(track => track.stop());
      }
    };
  }, [isVoiceMode]);

  const handleOpenChat = () => {
    setIsVoiceMode(true);
  };

  const handleVoiceSuccess = () => {
    if (recognitionRef.current) recognitionRef.current.stop();
    
    setIsVoiceMode(false);
    setIsChatMode(true);
    
    const userMessage = transcript.trim() ? transcript : "Hello, how are you?";
    setMessages(prev => [...prev, { role: 'user', content: userMessage }]);
    setTranscript('');

    const dummyResponses = [
      "Hi! I'm doing well. How can I help you today?",
      "I am LUCA. I'm here to assist you with anything you need. What's on your mind?",
      "That's an interesting perspective. Let's discuss it further.",
      "I can certainly help you with that. Here is what I found.",
      "I am an advanced artificial intelligence. I process information at incredible speeds!"
    ];
    const aiResponse = dummyResponses[Math.floor(Math.random() * dummyResponses.length)];

    setTimeout(() => {
      setMessages(prev => [...prev, { role: 'ai', content: aiResponse }]);
    }, 600);
  };

  const handleVoiceCancel = () => {
    setIsVoiceMode(false);
    setTranscript('');
    if (recognitionRef.current) recognitionRef.current.stop();
  };

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  return (
    <>
      <main className={`app-main ${isChatMode ? 'chat-mode' : 'fade-in'}`}>
        
        {/* Premium Background Layers */}
        <div className="ambient-background">
          <div className="ambient-colors"></div>
          <div className="ambient-texture"></div>
          <div className="ambient-valley-mask"></div>
        </div>

        {/* Top Area Cleaned */}
        {!isChatMode && !isVoiceMode && (
          <Starfield />
        )}

        {/* Center Content for Home and Voice Mode */}
        {(!isChatMode || isVoiceMode) && (
          <div className="center-content">
            {/* Logo removed as requested */}
            <h1 className="welcome-text fade-in-text">
              {isVoiceMode ? (transcript || 'Listening...') : 'Welcome'}
            </h1>
          </div>
        )}

        {/* Chat History */}
        {isChatMode && !isVoiceMode && (
          <div className="chat-history">
            {messages.map((msg, idx) => (
              <div key={idx} className={`message ${msg.role}`}>
                {msg.content}
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>
        )}

        {/* Bottom Search Bar (Always acts as a voice button) */}
        {!isVoiceMode && (
          <div className="bottom-bar-container slide-up">
            <div className="search-bar" onClick={handleOpenChat}>
              <span className="placeholder-text">Ask LUCA</span>
            </div>
          </div>
        )}

        {/* Voice Bottom Controls */}
        {isVoiceMode && (
          <div className="voice-container slide-up">
            <div className="voice-bottom-controls">
              <button className="voice-btn" aria-label="Cancel" onClick={handleVoiceCancel}>
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
              </button>
              
              <div className="voice-glow-btn" ref={buttonRef}></div>
              
              <button className="voice-btn" aria-label="Done" onClick={handleVoiceSuccess}>
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>
              </button>
            </div>
          </div>
        )}

      </main>

      <PWABadge />
    </>
  );
}

export default App;
