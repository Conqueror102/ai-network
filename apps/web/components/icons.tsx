// Decorative SVGs. All are aria-hidden; the surrounding element carries the label.

export function Mark() {
  // Two overlapping circles inside a ring: two people meeting, with the
  // shared lens (the match) filled in.
  return (
    <svg className="mark" viewBox="0 0 40 40" fill="none" aria-hidden="true">
      <defs>
        <clipPath id="mclip">
          <circle cx="15.6" cy="20" r="8.2" />
        </clipPath>
      </defs>
      <circle cx="20" cy="20" r="18.4" stroke="#0d1b30" strokeWidth="1.1" />
      <circle cx="24.4" cy="20" r="8.2" fill="#0d1b30" clipPath="url(#mclip)" />
      <circle cx="15.6" cy="20" r="8.2" stroke="#0d1b30" strokeWidth="2.2" />
      <circle cx="24.4" cy="20" r="8.2" stroke="#0d1b30" strokeWidth="2.2" />
    </svg>
  );
}

export function HomeIcon() {
  return (
    <svg viewBox="0 0 20 21" fill="none" aria-hidden="true">
      <path
        d="M2 8.4 10 2l8 6.4V18a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1z"
        stroke="#202940"
        strokeWidth="1.7"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function GridIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
      {[
        [1, 1],
        [11.6, 1],
        [1, 11.6],
        [11.6, 11.6],
      ].map(([x, y]) => (
        <rect key={`${x}-${y}`} x={x} y={y} width="7.4" height="7.4" rx="1.7" stroke="#202940" strokeWidth="1.7" />
      ))}
    </svg>
  );
}

export function Chevron() {
  return (
    <svg viewBox="0 0 18 18" fill="none" aria-hidden="true">
      <path d="m6.6 3.6 6 5.4-6 5.4" stroke="#fff" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function Play() {
  return (
    <svg viewBox="0 0 13 14" aria-hidden="true">
      <path d="M1.4 1.3 11.6 7 1.4 12.7z" fill="#0b1526" />
    </svg>
  );
}

export function Spark() {
  // The wingman: one large four-point spark with a small companion.
  return (
    <svg viewBox="0 0 30 39" fill="none" aria-hidden="true">
      <path
        d="M13 9.5c1.1 6.9 4 9.9 11 11-7 1.1-9.9 4-11 11-1.1-7-4-9.9-11-11 7-1.1 9.9-4.1 11-11z"
        stroke="#101c33"
        strokeWidth="2"
        strokeLinejoin="round"
      />
      <path
        d="M24.5 3.5c.4 2.6 1.5 3.7 4 4-2.5.4-3.6 1.5-4 4-.4-2.5-1.5-3.6-4-4 2.5-.3 3.6-1.4 4-4z"
        stroke="#101c33"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
    </svg>
  );
}
