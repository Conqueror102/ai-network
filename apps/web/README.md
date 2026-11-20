# apps/web — landing page

Next.js (App Router, TypeScript) marketing site, deployed on Vercel. Right now it
is a single full-viewport hero.

```bash
cd apps/web
npm install
npm run dev        # http://localhost:3000
npm run build
```

On Vercel, set the project's Root Directory to `apps/web`.

## How the hero is built

- **Design units.** The layout is a measured 1280×960 comp. Every size is
  `calc(N*var(--u))`, where `--u` is one comp pixel scaled to the viewport.
  Never write rem or px for layout. The background video stretches to the
  viewport; foreground elements keep their measured size.
- **Positioning.** On wide frames the wrapper divs are `display:contents` and
  each element is placed against `.card` with inline `--x/--y` (`.t` top,
  `.c` centre, `.b` bottom, `.r` right edge). `--sx` is a per-element optical
  horizontal scale.
- **Responsive tiers** are keyed to frame shape, not device width: desktop
  (≥ 87:80), compact (wrappers become a flex column; landscape keeps copy and
  panel side by side), and mobile (≤ 640px portrait, with a second floored
  scale `--t` for reading type and touch targets). Portrait frames collapse
  the nav into the burger menu.
- **Motion.** `html.pre` is added by an inline head script before first paint
  (skipped for reduced motion or without WAAPI). `components/HeroMotion.tsx`
  runs the entrance timeline, then removes the class so the resting frame is
  the plain CSS. The background video holds on frame 1 for reduced motion.

Files: `app/globals.css` (all layout), `app/page.tsx` (markup and copy),
`components/SiteHeader.tsx` (brand, nav, burger), `components/HeroMotion.tsx`.
