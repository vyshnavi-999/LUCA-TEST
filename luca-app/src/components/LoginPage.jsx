import React, { useState, useEffect } from 'react';
import './LoginPage.css';

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'http://127.0.0.1:8000';

const CLASS_OPTIONS = ['1st','2nd','3rd','4th','5th','6th','7th','8th','9th','10th','11th','12th','Staff'];

const LoginPage = ({ onLogin }) => {
  const [fullName,     setFullName]     = useState('');
  const [mobileNumber, setMobileNumber] = useState('');
  const [standard,     setStandard]     = useState('');
  const [isValid,      setIsValid]      = useState(false);
  const [loading,      setLoading]      = useState(false);
  const [error,        setError]        = useState('');

  useEffect(() => {
    const digitsOnly = mobileNumber.replace(/\D/g, '');
    setIsValid(
      fullName.trim().length > 0 &&
      digitsOnly.length === 10 &&
      standard.length > 0
    );
  }, [fullName, mobileNumber, standard]);

  const handleMobileChange = (e) => {
    const val = e.target.value.replace(/\D/g, '');
    if (val.length <= 10) setMobileNumber(val);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!isValid || loading) return;

    setLoading(true);
    setError('');

    try {
      const res = await fetch(`${BACKEND_URL}/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name:           fullName.trim(),
          identifier:     mobileNumber.replace(/\D/g, ''),
          class_standard: standard,
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        setError(data.detail || 'Login failed. Please try again.');
        setLoading(false);
        return;
      }

      const user = {
        fullName:     data.name || fullName.trim(),
        mobileNumber: mobileNumber.replace(/\D/g, ''),
        standard,
        userId:       data.user_id,
        createdAt:    new Date().toISOString(),
      };
      localStorage.setItem('lucaUser',      JSON.stringify(user));
      localStorage.setItem('vc_user_id',    data.user_id);
      localStorage.setItem('vc_identifier', data.identifier);
      localStorage.setItem('vc_name',       data.name || '');

      onLogin(user);

    } catch {
      setError('Could not reach the backend. Check your connection.');
    }

    setLoading(false);
  };

  return (
    <div className="login-page-container">
      <div className="login-card">
        <form id="luca-login-form" onSubmit={handleSubmit} className="login-form">

          <div className="login-field">
            <label htmlFor="fullName">FULL NAME *</label>
            <input
              id="fullName"
              type="text"
              placeholder="Full Name"
              value={fullName}
              onChange={e => setFullName(e.target.value)}
              className="login-input"
              autoComplete="name"
            />
          </div>

          <div className="login-field">
            <label htmlFor="mobileNumber">MOBILE NUMBER *</label>
            <input
              id="mobileNumber"
              type="tel"
              placeholder="10-digit mobile number"
              value={mobileNumber}
              onChange={handleMobileChange}
              className="login-input"
              autoComplete="tel"
            />
          </div>

          <div className="login-field">
            <label htmlFor="standard">CLASS / STANDARD *</label>
            <div className="login-select-wrapper">
              <select
                id="standard"
                value={standard}
                onChange={e => setStandard(e.target.value)}
                className="login-select"
                required
              >
                <option value="" disabled>Select your class</option>
                {CLASS_OPTIONS.map(c => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
              <span className="login-select-arrow" aria-hidden="true">▾</span>
            </div>
            <p className="login-helper">If you are a teacher, select Staff.</p>
          </div>

          {error && <p className="login-error">{error}</p>}

        </form>
      </div>

      {/* Submit button lives outside the card, anchored in the bottom dock */}
      <div className="bottom-dock slide-up">
        <button
          type="submit"
          form="luca-login-form"
          className="login-submit-btn"
          disabled={!isValid || loading}
        >
          {loading ? 'Signing in…' : 'Login'}
        </button>
      </div>
    </div>
  );
};

export default LoginPage;
