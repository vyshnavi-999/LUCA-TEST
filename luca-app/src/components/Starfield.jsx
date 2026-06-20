import React, { useMemo } from 'react';
import './Starfield.css';

const Starfield = ({ isFullScreen = false }) => {
  const stars = useMemo(() => {
    const generatedStars = [];
    // Increased to 150 stars to maintain the same density across 100vh
    for (let i = 0; i < 150; i++) {
      const rand = Math.random();
      let size = 1.5;
      if (rand > 0.9) size = 2.5;
      else if (rand > 0.7) size = 2;
      else size = Math.random() * 0.5 + 1;

      const baseOpacity = Math.random() * 0.5 + 0.3;
      const hasGlow = Math.random() > 0.8;

      generatedStars.push({
        id: i,
        top: Math.random() * 100, // 0-100% of 100vh
        left: Math.random() * 100, // 0-100vw
        size,
        baseOpacity,
        hasGlow,
      });
    }
    return generatedStars;
  }, []);

  return (
    <div className={`home-starfield-container ${isFullScreen ? 'full-screen' : 'masked'}`}>
      {stars.map((star) => (
        <svg
          key={star.id}
          className={`star-svg ${star.hasGlow ? 'glow' : ''}`}
          style={{
            top: `${star.top}%`,
            left: `${star.left}%`,
            width: `${star.size}px`,
            height: `${star.size}px`,
            opacity: star.baseOpacity,
          }}
          viewBox="0 0 24 24"
        >
          {/* 4-pointed star shape (✦ style) using Quadratic Bezier Curves */}
          <path d="M12 0 Q12 12 24 12 Q12 12 12 24 Q12 12 0 12 Q12 12 12 0 Z" fill="currentColor" />
        </svg>
      ))}
    </div>
  );
};

export default Starfield;
