"use client";

import { useEffect } from "react";

const EXPO = "cubic-bezier(.16,1,.3,1)";
const SOFT = "cubic-bezier(.22,.7,.25,1)";
const GLASS = "cubic-bezier(.2,.75,.28,1)";

/**
 * Entrance timeline (WAAPI) and background-plate control.
 * Renders nothing. The timeline runs once, then removes html.pre and cancels
 * its animations so the resting frame is the authored CSS.
 */
export function HeroMotion() {
  // Entrance timeline. Four behaviours: masked rise, quiet lift, glass settle, accent.
  useEffect(() => {
    const root = document.documentElement;
    if (!root.classList.contains("pre")) return;

    const s = window.matchMedia("(max-width: 640px)").matches ? 0.86 : 1; // restraint on phones
    const running: Animation[] = [];
    const q = (sel: string) => document.querySelector<HTMLElement>(sel);
    const qa = (sel: string) => Array.from(document.querySelectorAll<HTMLElement>(sel));

    const animate = (el: Element | null, frames: Keyframe[], dur: number, delay: number, easing: string) => {
      if (!el) return;
      running.push(el.animate(frames, { duration: dur * s, delay: delay * s, easing, fill: "both" }));
    };
    const rise = (el: Element | null, delay: number, dur: number) =>
      animate(
        el,
        [
          { clipPath: "inset(100% 0 -14% 0)", translate: "0 .16em" },
          { clipPath: "inset(-18% 0 -14% 0)", translate: "0 0" },
        ],
        dur,
        delay,
        EXPO,
      );
    const lift = (el: Element | null, delay: number, dist = ".7em", dur = 560) =>
      animate(el, [{ opacity: 0, translate: "0 " + dist }, { opacity: 1, translate: "0 0" }], dur, delay, SOFT);
    const settle = (el: Element | null, delay: number, dur = 760, from = 0.985, dist = "1.1em") =>
      animate(
        el,
        [
          { opacity: 0, scale: String(from), translate: "0 " + dist },
          { opacity: 1, scale: "1", translate: "0 0" },
        ],
        dur,
        delay,
        GLASS,
      );

    const h1 = qa("h1 .sx");
    const nums = qa(".num");
    const lbls = qa(".lbl");

    lift(q(".brand"), 60, ".55em", 600);
    settle(q(".nav"), 150, 700, 0.99, ".5em");
    settle(q(".cta"), 200, 700, 0.985, ".5em");
    settle(q(".burger"), 150, 700, 0.9, ".4em");
    lift(q(".eyebrow"), 300, ".8em", 520);
    rise(h1[0], 380, 980);
    rise(h1[1], 470, 980);
    settle(q(".play"), 720, 640, 0.88, ".3em");
    lift(q(".tag"), 770, ".7em", 560);
    settle(q(".panel"), 800, 880, 0.982, "1.4em");
    animate(q(".badge"), [{ scale: ".86" }, { scale: "1" }], 700, 1020, EXPO);
    animate(q(".dot"), [{ scale: "0" }, { scale: "1" }], 520, 1080, EXPO);
    animate(q(".track i"), [{ scale: "0 1" }, { scale: "1 1" }], 820, 1120, EXPO);
    rise(nums[0], 920, 860);
    rise(nums[1], 990, 860);
    lift(lbls[0], 1030, ".6em", 520);
    lift(lbls[1], 1075, ".6em", 520);
    animate(q(".slash"), [{ scale: "1 0" }, { scale: "1 1" }], 700, 1010, EXPO);
    settle(q(".meet"), 1140, 820, 0.985, "1.2em");

    let cancelled = false;
    Promise.all(running.map((a) => a.finished.catch(() => {}))).then(() => {
      if (cancelled) return;
      root.classList.remove("pre");
      running.forEach((a) => a.cancel());
      running.length = 0;
    });

    // Dev StrictMode mounts twice: drop this run without touching html.pre
    // so the second mount replays the timeline from its pre-state.
    return () => {
      cancelled = true;
      running.forEach((a) => a.cancel());
    };
  }, []);

  // Hold the plate on frame 1 for anyone who asked for less motion, follow the
  // preference live, and resume a plate that loaded in a background tab.
  useEffect(() => {
    const v = document.querySelector<HTMLVideoElement>("video.bg");
    if (!v) return;
    const q = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => {
      if (q.matches) {
        v.pause();
        v.currentTime = 0;
      } else v.play().catch(() => {});
    };
    const onVis = () => {
      if (!document.hidden) sync();
    };
    q.addEventListener("change", sync);
    document.addEventListener("visibilitychange", onVis);
    v.addEventListener("canplay", sync);
    sync();
    return () => {
      q.removeEventListener("change", sync);
      document.removeEventListener("visibilitychange", onVis);
      v.removeEventListener("canplay", sync);
    };
  }, []);

  return null;
}
