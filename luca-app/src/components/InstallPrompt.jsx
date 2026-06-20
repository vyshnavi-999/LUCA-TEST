import React from 'react';
import { useInstallPrompt } from '../hooks/useInstallPrompt';

export function InstallPrompt() {
  const { isInstallable, isInstalled, handleInstallClick } = useInstallPrompt();

  if (!isInstallable || isInstalled) {
    return null;
  }

  return (
    <div className="install-prompt">
      <div className="install-prompt-info">
        <h3>LUCA</h3>
        <p className="text-muted">Install LUCA on your home screen for quick and easy access when you're on the go.</p>
      </div>
      <div className="install-prompt-actions">
        <button className="btn-primary" onClick={handleInstallClick}>
          Add to Home Screen
        </button>
      </div>
    </div>
  );
}
