"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Chevron, GridIcon, HomeIcon, Mark } from "./icons";

/**
 * Header row: brand, burger, and the menu (nav pill + primary CTA).
 * On landscape frames the menu is display:contents and the burger is hidden;
 * on portrait frames the menu collapses into a glass sheet behind the burger.
 */
export function SiteHeader() {
  const [open, setOpen] = useState(false);
  const burgerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const close = useCallback((returnFocus = false) => {
    setOpen(false);
    if (returnFocus) burgerRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      const t = e.target as Node;
      if (burgerRef.current?.contains(t) || menuRef.current?.contains(t)) return;
      close();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close(true);
    };
    document.addEventListener("click", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("click", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, close]);

  // Landscape never collapses: close the sheet if the frame turns landscape.
  useEffect(() => {
    const mq = window.matchMedia("(min-aspect-ratio: 1/1)");
    const onChange = (e: MediaQueryListEvent) => {
      if (e.matches) close();
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [close]);

  const onMenuClick = (e: React.MouseEvent) => {
    if ((e.target as Element).closest("a")) close();
  };

  return (
    <div className="row">
      <a className="brand l t" style={{ "--x": 68, "--y": 47 } as React.CSSProperties} href="#" aria-label="AiNetwork home">
        <Mark />
        <b className="sx" style={{ "--sx": 0.894 } as React.CSSProperties}>
          AiNetwork
        </b>
      </a>
      <button
        ref={burgerRef}
        className="burger"
        type="button"
        aria-label={open ? "Close menu" : "Open menu"}
        aria-expanded={open}
        aria-controls="site-menu"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
      >
        <i />
        <i />
      </button>
      <div ref={menuRef} className="menu" id="site-menu" data-open={open ? "" : undefined} onClick={onMenuClick}>
        <nav className="nav" aria-label="Primary">
          <i className="n-home">
            <HomeIcon />
          </i>
          <a className="n-attendees" href="#attendees">
            <span>Attendees</span>
          </a>
          <hr className="n-div" />
          <i className="n-grid">
            <GridIcon />
          </i>
          <a className="n-organizers" href="#organizers">
            <span>Organizers</span>
          </a>
        </nav>
        <a className="cta l t r" style={{ "--x": 58, "--y": 30 } as React.CSSProperties} href="#host">
          <span>Host an event</span>
          <i className="knob">
            <Chevron />
          </i>
        </a>
      </div>
    </div>
  );
}
