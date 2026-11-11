// Shared icon set and inline illustrations (no external images, so nothing to load or break).
const PATHS: Record<string, string> = {
  home: "M3 11l9-8 9 8M5 10v10h14V10",
  shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3z",
  bell: "M6 8a6 6 0 1112 0c0 7 3 8 3 8H3s3-1 3-8M10 20a2 2 0 004 0",
  lock: "M5 11h14v10H5zM8 11V7a4 4 0 018 0v4",
  building: "M4 21V5l8-3v19M20 21V10l-8-3M3 21h18M8 8h.01M8 12h.01M8 16h.01M16 14h.01M16 18h.01",
  check: "M5 12l5 5 9-10",
  clock: "M12 7v5l3 2M21 12a9 9 0 11-18 0 9 9 0 0118 0z",
  briefcase: "M3 8h18v12H3zM8 8V5h8v3M3 13h18",
  clipboard: "M9 4h6v3H9zM7 5H5v16h14V5h-2M9 14l2 2 4-4",
  wallet: "M3 7h16a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2zM3 7V6a2 2 0 012-2h11M17 14h.01",
  chart: "M4 20V4M4 20h16M8 16v-5M12 16V8M16 16v-3",
  customer: "M12 12a4 4 0 100-8 4 4 0 000 8zM4 21a8 8 0 0116 0",
  wrench: "M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z",
  pin: "M12 21s-7-6-7-11a7 7 0 1114 0c0 5-7 11-7 11zM12 12a2 2 0 100-4 2 2 0 000 4z",
  badge: "M4 5h16v14H4zM9 11a2 2 0 100-4 2 2 0 000 4zM6 17a3 3 0 016 0M14 9h4M14 13h4",
  users: "M16 20v-1a4 4 0 00-4-4H7a4 4 0 00-4 4v1M9.5 11a3.5 3.5 0 100-7 3.5 3.5 0 000 7zM21 20v-1a4 4 0 00-3-3.9M16 4.1a3.5 3.5 0 010 6.8",
  list: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  file: "M6 3h8l4 4v14H6zM14 3v4h4M9 13h6M9 17h6",
  star: "M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z",
  plus: "M12 5v14M5 12h14",
  x: "M6 6l12 12M18 6L6 18",
  arrow: "M5 12h14M13 6l6 6-6 6",
  sun: "M12 17a5 5 0 100-10 5 5 0 000 10zM12 1v3M12 20v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M1 12h3M20 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1",
  moon: "M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z",
  info: "M12 8h.01M11 12h1v5h1M21 12a9 9 0 11-18 0 9 9 0 0118 0z",
};

export const Icon = ({ name, size = 20 }: { name: string; size?: number }) => (
  <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="ico">
    <path d={PATHS[name] ?? ""} />
  </svg>
);

const grid = (x: number, y: number, cols: number, rows: number) =>
  Array.from({ length: cols * rows }, (_, i) => ({ x: x + (i % cols) * 15, y: y + Math.floor(i / cols) * 17 }));

// A small city skyline with a crane, drawn on the dark gradient backgrounds.
export const HeroArt = () => {
  const wins = [...grid(30, 84, 3, 4), ...grid(92, 54, 3, 6), ...grid(164, 98, 2, 4), ...grid(226, 74, 3, 5)];
  return (
    <svg viewBox="0 0 320 170" className="art" aria-hidden="true">
      <circle cx="262" cy="36" r="24" fill="#ff8a3d" opacity=".95" />
      <g fill="#ffffff" opacity=".13">
        <rect x="20" y="76" width="56" height="94" rx="5" />
        <rect x="82" y="46" width="62" height="124" rx="5" />
        <rect x="154" y="90" width="50" height="80" rx="5" />
        <rect x="216" y="66" width="64" height="104" rx="5" />
      </g>
      <g fill="#ffffff" opacity=".5">
        {wins.map((w, i) => <rect key={i} x={w.x} y={w.y} width="8" height="9" rx="1.5" />)}
      </g>
      <path d="M118 46V10h96M214 10v24M118 16L92 46" stroke="#ff8a3d" strokeWidth="3" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      <rect x="206" y="34" width="16" height="10" rx="2" fill="#ff8a3d" />
      <rect x="0" y="168" width="320" height="2" fill="#ffffff" opacity=".3" />
    </svg>
  );
};

export const EmptyArt = () => (
  <svg viewBox="0 0 120 84" width="120" height="84" className="empty-art" aria-hidden="true">
    <g fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" opacity=".55">
      <path d="M14 78V30l30-10v58M44 78V40l30-8v46M74 78V24l32 10v44M8 78h104" />
      <path d="M24 42h.01M24 54h.01M24 66h.01M58 52h.01M58 64h.01M88 46h.01M88 58h.01M88 70h.01" strokeWidth="4" />
    </g>
    <circle cx="96" cy="12" r="7" fill="#f26a1b" opacity=".85" />
  </svg>
);

// Left panel of the sign-in page.
export const AuthArt = () => (
  <aside className="auth-art">
    <div className="brand"><span className="logo">D</span><span>Duale <b>BuildLink</b></span></div>
    <h2>Skilled trades, connected across Puntland.</h2>
    <ul>
      <li><Icon name="shield" size={18} /> Verified companies and technicians</li>
      <li><Icon name="pin" size={18} /> Jobs in Garowe, Bosaso, Galkayo and Qardho</li>
      <li><Icon name="wallet" size={18} /> A clear record of every payment</li>
    </ul>
    <div className="auth-skyline"><HeroArt /></div>
  </aside>
);
