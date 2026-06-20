import React from 'react';
import { useRegisterSW } from 'virtual:pwa-register/react';
import './PWABadge.css';

export function PWABadge() {
  const {
    offlineReady: [offlineReady, setOfflineReady],
    needRefresh: [needRefresh, setNeedRefresh],
    updateServiceWorker,
  } = useRegisterSW({
    onRegistered(r) {
      console.log('SW Registered: ', r);
    },
    onRegisterError(error) {
      console.log('SW registration error', error);
    },
  });

  const close = () => {
    setOfflineReady(false);
    setNeedRefresh(false);
  };

  if (!offlineReady && !needRefresh) {
    return null;
  }

  return (
    <div className="pwa-badge" role="alert" aria-labelledby="toast-message">
      <div className="pwa-toast">
        <div className="pwa-message">
          {offlineReady
            ? <span>App is ready to work offline</span>
            : <span>New update available! Click reload to apply.</span>}
        </div>
        <div className="pwa-buttons">
          {needRefresh && (
            <button className="btn-primary" onClick={() => updateServiceWorker(true)}>
              Reload
            </button>
          )}
          <button className="btn-secondary" onClick={() => close()}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
