import photo from "../assets/hero-jeju-rotorless.jpg";
import blade1 from "../assets/hero-blade-1.png";
import blade2 from "../assets/hero-blade-2.png";
import blade3 from "../assets/hero-blade-3.png";
import blade4 from "../assets/hero-blade-4.png";
import blade5 from "../assets/hero-blade-5.png";

/**
 * Hero photo whose turbine blades rotate slowly. Each rotor reuses one real
 * blade cut from the original photo (hero-blade-N.png, pointing up, root at
 * the hub), drawn three times 120° apart. Coordinates are the photo's own
 * pixels (1536 × 864), so the overlay stays aligned at any screen size.
 */
const turbines = [
  {
    src: blade1,
    x: 123,
    y: 419,
    len: 134.6,
    half: 13,
    phase: 78.5,
    seconds: 19,
  },
  { src: blade2, x: 218, y: 538, len: 68.6, half: 6, phase: 98, seconds: 15 },
  { src: blade3, x: 307.5, y: 589, len: 41, half: 3, phase: 0, seconds: 12 },
  {
    src: blade4,
    x: 1427,
    y: 505,
    len: 110.9,
    half: 12,
    phase: 17.4,
    seconds: 21,
  },
  {
    src: blade5,
    x: 1323,
    y: 589,
    len: 58.1,
    half: 6,
    phase: 86.8,
    seconds: 16,
  },
];

export function HeroTurbines() {
  return (
    <svg
      className="hero-scene"
      viewBox="0 0 1536 864"
      preserveAspectRatio="xMidYMax slice"
      aria-hidden="true"
      focusable="false"
    >
      <image href={photo} width="1536" height="864" />
      {turbines.map((t) => (
        <g
          key={t.src}
          transform={`translate(${t.x} ${t.y}) rotate(${t.phase})`}
        >
          <g
            className="hero-rotor"
            style={{ animationDuration: `${t.seconds}s` }}
          >
            {[0, 120, 240].map((angle) => (
              <image
                key={angle}
                href={t.src}
                x={-t.half}
                y={-t.len}
                width={t.half * 2}
                height={t.len}
                transform={`rotate(${angle})`}
              />
            ))}
          </g>
        </g>
      ))}
    </svg>
  );
}
