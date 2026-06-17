import React, { useMemo } from 'react';
import './Starfield.css';

const Starfield = () => {
  const stars = useMemo(() => {
    const generatedStars = [];
    for (let i = 0; i < 70; i++) {
      generatedStars.push({
        id: i,
        top: Math.random() * 100, // 0-100%
        left: Math.random() * 100, // 0-100%
        // We use 2-4px. At 1px, a 5-point star is impossible to render physically on screen pixels.
        // 2px is extremely tiny, mimicking a 1px dot visually but with enough sub-pixels to suggest a star.
        size: Math.random() > 0.85 ? 4 : (Math.random() > 0.6 ? 3 : 2),
        baseOpacity: Math.random() * 0.4 + 0.2, // 0.2 to 0.6
        isTwinkling: Math.random() > 0.5, // 50% chance to twinkle
        twinkleDelay: Math.random() * 5, // 0-5s stagger
        twinkleDuration: Math.random() * 4 + 3, // 3-7s twinkle speed
      });
    }
    return generatedStars;
  }, []);

  return (
    <div className="home-starfield-container">
      {stars.map((star) => (
        <svg
          key={star.id}
          className={`star-svg ${star.isTwinkling ? 'twinkling' : ''}`}
          style={{
            top: `${star.top}%`,
            left: `${star.left}%`,
            width: `${star.size}px`,
            height: `${star.size}px`,
            opacity: star.baseOpacity,
            '--twinkle-delay': `${star.twinkleDelay}s`,
            '--twinkle-duration': `${star.twinkleDuration}s`,
            '--base-opacity': star.baseOpacity,
          }}
          viewBox="0 0 24 24"
        >
          {/* Authentic 5-pointed star shape */}
          <path d="M12 .587l3.668 7.568 8.332 1.151-6.064 5.828 1.48 8.279-7.416-3.967-7.417 3.967 1.481-8.279-6.064-5.828 8.332-1.151z" fill="currentColor" />
        </svg>
      ))}
    </div>
  );
};

export default Starfield;
