import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import logo from "../assets/asap_black.png";
import {
  ACCESS_MODE_STORAGE_KEY,
  EXPERT_ACCESS_MODE,
  GUEST_ACCESS_MODE,
  IsValidExpertAccessCode,
} from "../lib/expertAccess";

function GlobeIllustration() {
  return (
    <div className="introduction-globe-wrap" aria-hidden="true">
      <div className="introduction-orbit introduction-orbit-outer" />
      <div className="introduction-orbit introduction-orbit-inner" />
      <svg className="introduction-globe" viewBox="0 0 600 600">
        <defs>
          <radialGradient id="globe-surface" cx="35%" cy="25%" r="75%">
            <stop offset="0%" stopColor="#5edcff" />
            <stop offset="42%" stopColor="#2468d8" />
            <stop offset="100%" stopColor="#091b54" />
          </radialGradient>
          <linearGradient id="globe-land" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#9af4db" />
            <stop offset="100%" stopColor="#31bfa2" />
          </linearGradient>
          <linearGradient id="plane-fill" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#ffffff" />
            <stop offset="100%" stopColor="#b8e9ff" />
          </linearGradient>
          <linearGradient id="plane-trail" gradientUnits="userSpaceOnUse" x1="0" y1="45" x2="0" y2="190">
            <stop offset="0%" stopColor="#fff1f4" />
            <stop offset="18%" stopColor="#ff345f" />
            <stop offset="100%" stopColor="#ff003c" stopOpacity="0" />
          </linearGradient>
          <g id="globe-landmasses">
            <path d="M151 199c35-54 104-82 151-69l18 33-27 26-42 5-14 25-42 3-31 30-29-12 16-41Z" />
            <path d="M262 246l43-22 48 13 20 37-18 29 19 35-31 55-20 69-28-8-7-61-32-39 12-34-24-33 18-41Z" />
            <path d="M372 169l57 24 34 44-13 31-46-7-18-25-43-10-11-29 40-28Z" />
            <path d="M406 313l47 8 29 34-18 35-38 7-24-29-21-17 25-38Z" />
            <path d="M111 352l47-29 43 13 17 31-24 21-7 50-38 30-21-47-36-28 19-41Z" />
            <path d="M474 208l47-14 25 29-15 24-42 3-27-18 12-24Z" />
          </g>
          <clipPath id="globe-clip">
            <circle cx="300" cy="300" r="205" />
          </clipPath>
          <filter id="globe-glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="14" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <circle cx="300" cy="300" r="226" fill="none" stroke="#4fd9ff" strokeOpacity=".16" strokeWidth="2" />
        <circle cx="300" cy="300" r="207" fill="url(#globe-surface)" filter="url(#globe-glow)" />

        <g clipPath="url(#globe-clip)">
          <g className="introduction-globe-axis">
            <g className="introduction-globe-grid" fill="none" stroke="#b9efff" strokeOpacity=".2">
              <ellipse cx="300" cy="300" rx="205" ry="72" />
              <ellipse cx="300" cy="300" rx="205" ry="142" />
              <ellipse cx="300" cy="300" rx="78" ry="205" />
              <ellipse cx="300" cy="300" rx="145" ry="205" />
            </g>
            <g className="introduction-globe-terrain" fill="url(#globe-land)" opacity=".9">
              <use href="#globe-landmasses" x="-480" />
              <use href="#globe-landmasses" />
              <use href="#globe-landmasses" x="480" />
            </g>
          </g>
          <circle cx="230" cy="210" r="150" fill="#ffffff" opacity=".07" />
        </g>

        <circle cx="300" cy="300" r="205" fill="none" stroke="#a7edff" strokeOpacity=".7" strokeWidth="3" />
        <path d="M111 205C194 57 432 44 512 222" fill="none" stroke="#92dcff" strokeDasharray="8 12" strokeOpacity=".55" strokeWidth="2" />

        <g className="introduction-airplane" transform="translate(300 300) rotate(34)">
          <path
            className="introduction-airplane-trail-glow"
            d="M0 42V190"
            fill="none"
            stroke="#ff174f"
            strokeLinecap="round"
            strokeWidth="18"
          />
          <path
            className="introduction-airplane-trail-core"
            d="M0 42V190"
            fill="none"
            stroke="url(#plane-trail)"
            strokeLinecap="round"
            strokeWidth="4"
          />
          <path
            d="M0-48 9-13 47 6v11L9 10 6 36l15 12v7L0 49l-21 6v-7l15-12 6-26-38 7V6l38-19 9-35Z"
            fill="url(#plane-fill)"
            stroke="#ffffff"
            strokeLinejoin="round"
            strokeWidth="3"
          />
        </g>
      </svg>
      <span className="introduction-orbit-label">SEOUL · EU</span>
    </div>
  );
}

function IntroductionHero() {
  return (
    <section className="introduction-hero" id="introduction-top">
      <header className="introduction-header">
        <a href="#introduction-top" className="introduction-logo-link" aria-label="ASAP 홈">
          <span
            className="introduction-logo"
            style={{ WebkitMaskImage: `url(${logo})`, maskImage: `url(${logo})` }}
          />
        </a>
      </header>

      <div className="introduction-hero-content">
        <div className="introduction-hero-copy">
          <p className="introduction-eyebrow">KOREA TO EUROPE · EXPORT ASSISTANT</p>
          <h1>
            유럽 수출의 복잡함을,
            <span>하나의 흐름으로.</span>
          </h1>
          <p className="introduction-summary">
            제품 정보를 바탕으로 품목분류 후보부터 규제·인증·필요 서류까지
            한눈에 검토할 수 있도록 정리합니다.
          </p>
          <a className="introduction-primary-action" href="#access-modes">
            분석 모드 선택하기
            <span aria-hidden="true">↓</span>
          </a>
        </div>
        <GlobeIllustration />
      </div>

      <a className="introduction-scroll-cue" href="#access-modes">
        <span>SCROLL TO EXPLORE</span>
        <i aria-hidden="true" />
      </a>
    </section>
  );
}

function AccessModeSelection() {
  const navigate = useNavigate();
  const [accessCode, setAccessCode] = useState("");
  const [errorMessage, setErrorMessage] = useState("");

  function handleExpertSubmit(event) {
    event.preventDefault();

    if (IsValidExpertAccessCode(accessCode)) {
      window.sessionStorage.setItem(ACCESS_MODE_STORAGE_KEY, EXPERT_ACCESS_MODE);
      navigate("/classification");
      return;
    }

    setErrorMessage("접근 코드를 다시 확인해 주세요.");
  }

  return (
    <section className="access-mode-section" id="access-modes" aria-labelledby="access-mode-title">
      <div className="access-mode-heading">
        <p>CHOOSE YOUR EXPERIENCE</p>
        <h2 id="access-mode-title">어떤 방식으로 시작하시겠어요?</h2>
        <span>목적에 맞는 화면으로 바로 이동합니다.</span>
      </div>

      <div className="access-mode-stage">
        <article className="access-mode-panel access-mode-guest">
          <div className="access-mode-content">
            <span className="access-mode-number">01</span>
            <p className="access-mode-kicker">GUEST MODE</p>
            <h3>빠르고 간편하게</h3>
            <p className="access-mode-description">
              질문 한 줄로 핵심 품목분류 후보와 준비 항목을 간단히 확인합니다.
            </p>
            <Link
              className="access-mode-action access-mode-guest-action"
              to="/consumer"
              onClick={() => window.sessionStorage.setItem(ACCESS_MODE_STORAGE_KEY, GUEST_ACCESS_MODE)}
            >
              게스트로 시작하기
              <span aria-hidden="true">→</span>
            </Link>
          </div>
        </article>

        <article className="access-mode-panel access-mode-expert">
          <div className="access-mode-content">
            <span className="access-mode-number">02</span>
            <p className="access-mode-kicker">EXPERT MODE</p>
            <h3>근거까지 깊이 있게</h3>
            <p className="access-mode-description">
              단계별 분류 과정과 실행 근거를 프로젝트 화면에서 상세히 검토합니다.
            </p>
            <form className="expert-access-form" onSubmit={handleExpertSubmit} noValidate>
              <label htmlFor="expert-access-code">전문가 접근 코드</label>
              <div className="expert-access-controls">
                <input
                  id="expert-access-code"
                  type="password"
                  value={accessCode}
                  aria-describedby={errorMessage ? "expert-access-error" : undefined}
                  aria-invalid={Boolean(errorMessage)}
                  autoComplete="off"
                  placeholder="접근 코드를 입력하세요"
                  onChange={(event) => {
                    setAccessCode(event.target.value);
                    setErrorMessage("");
                  }}
                />
                <button type="submit" aria-label="전문가 모드로 이동">
                  →
                </button>
              </div>
              {errorMessage ? (
                <p className="expert-access-error" id="expert-access-error" role="alert">
                  {errorMessage}
                </p>
              ) : null}
            </form>
          </div>
        </article>
        <span className="access-mode-divider" aria-hidden="true" />
      </div>
    </section>
  );
}

export default function IntroductionPage() {
  return (
    <div className="introduction-page">
      <IntroductionHero />
      <AccessModeSelection />
    </div>
  );
}
