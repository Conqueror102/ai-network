import type { CSSProperties } from "react";
import { HeroMotion } from "@/components/HeroMotion";
import { SiteHeader } from "@/components/SiteHeader";
import { Chevron, Play, Spark } from "@/components/icons";

// Background plate: a glass sphere on a pale blue-white studio backdrop.
const PLATE_POSTER =
  "https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260912_105822_bf7c2d53-9957-4521-bbbf-7c1ab7a70130.png";
const PLATE_VIDEO =
  "https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260912_105953_21ad8049-9088-4a00-bad3-aee6b5575a2b.mp4";

/** Inline design-unit position: --x/--y in comp pixels, --sx optical width. */
const pos = (v: Record<string, number>) => v as unknown as CSSProperties;

export default function Home() {
  return (
    <main className="page">
      <div className="card">
        <video
          className="bg"
          autoPlay
          muted
          loop
          playsInline
          preload="auto"
          disablePictureInPicture
          aria-hidden="true"
          poster={PLATE_POSTER}
          src={PLATE_VIDEO}
        />
        <div className="tint" />

        <div className="stack">
          <SiteHeader />

          <div className="hero-blk">
            <p className="eyebrow l c sx" style={pos({ "--x": 65.7, "--y": -209.2, "--sx": 0.9293 })}>
              Your AI networking wingman
            </p>
            <h1 className="l c" style={pos({ "--x": 62.6, "--y": -167.3 })}>
              <span className="sx" style={pos({ "--sx": 0.9431 })}>
                Network Smarter
              </span>
              <br />
              <span className="sx" style={pos({ "--sx": 0.9792 })}>
                At Every Event
              </span>
            </h1>
            <div className="tagrow">
              <span className="play l c" style={pos({ "--x": 66, "--y": 34 })} aria-hidden="true">
                <Play />
              </span>
              <span className="tag l c sx" style={pos({ "--x": 131, "--y": 48.7, "--sx": 0.8973 })}>
                Rejection-proof by design. Declines stay silent.
              </span>
            </div>
            <aside className="panel l c r" style={pos({ "--x": 58, "--y": -165 })} aria-label="AI wingman">
              <span className="p-title sx" style={pos({ "--sx": 0.8707 })}>
                Wingman
              </span>
              <i className="dot" />
              <span className="badge">
                <Spark />
              </span>
              <p className="p-sub sx" style={pos({ "--sx": 0.8899 })}>
                Two-way
                <br />
                Goal
                <br />
                Matching
              </p>
              <div className="scale" aria-hidden="true">
                <span>Goal</span>
                <span>Match</span>
                <span>Intro</span>
                <span>Meet</span>
              </div>
              <div className="track" aria-hidden="true">
                <i />
              </div>
            </aside>
          </div>

          <div className="row">
            <div className="stats">
              <div className="stat">
                <span className="num l b sx" style={pos({ "--x": 64, "--y": 60.4, "--sx": 1 })}>
                  90s
                </span>
                <span className="lbl l b sx" style={pos({ "--x": 244, "--y": 73.2, "--sx": 0.9634 })}>
                  From sign-up
                  <br />
                  to the
                  <br />
                  event room
                </span>
              </div>
              <span className="slash l b" style={pos({ "--x": 388, "--y": 76 })} aria-hidden="true" />
              <div className="stat">
                <span className="num l b sx" style={pos({ "--x": 450, "--y": 60.4, "--sx": 0.9858 })}>
                  100%
                </span>
                <span className="lbl l b sx" style={pos({ "--x": 705, "--y": 96.7, "--sx": 0.9209 })}>
                  Double
                  <br />
                  opt-in intros
                </span>
              </div>
            </div>
            <a className="meet l b r" style={pos({ "--x": 59, "--y": 66 })} href="#wingman">
              <span className="thumb">
                {/* eslint-disable-next-line @next/next/no-img-element -- decorative crop of the plate poster */}
                <img alt="" style={{ objectPosition: "60% 50%" }} src={PLATE_POSTER} />
              </span>
              <b>Meet Wingman</b>
              <i className="knob">
                <Chevron />
              </i>
            </a>
          </div>
        </div>
      </div>
      <HeroMotion />
    </main>
  );
}
