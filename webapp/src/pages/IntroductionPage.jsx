import { ArrowUpRight } from "lucide-react";
import { Link } from "react-router-dom";
import HeroStorySequence from "../components/introduction/HeroStorySequence";
import logo from "../assets/asap_black.png";

function IntroductionHero() {
  return (
    <section className="introduction-hero" aria-labelledby="introduction-heading">
      <header className="introduction-header">
        <Link to="/" className="introduction-logo-link" aria-label="ASAP 홈">
          <img className="introduction-logo" src={logo} alt="ASAP" />
        </Link>
        <p className="introduction-header-meta">
          <span>EU EXPORT INTELLIGENCE</span>
          <span>SEOUL · 2026</span>
        </p>
      </header>

      <div className="introduction-editorial-rule" aria-hidden="true" />

      <div className="introduction-hero-content">
        <article className="introduction-hero-copy">
          <p className="introduction-eyebrow">KOREA TO EUROPE · TRADE COMPLIANCE</p>
          <h1 id="introduction-heading">
            유럽 수출의 복잡함을,
            <span>하나의 흐름으로.</span>
          </h1>
          <p className="introduction-summary">
            상품 근거 수집부터 관세코드 후보 검토와 수출 서류 안내까지,
            흩어진 판단 과정을 하나의 분석 흐름으로 연결합니다.
          </p>
          <Link className="introduction-primary-action" to="/classification">
            전문가 분석 시작하기
            <ArrowUpRight aria-hidden="true" />
          </Link>
        </article>

        <section className="introduction-figure" aria-label="상품 분류와 서류 검토 흐름">
          <HeroStorySequence />
          <p className="introduction-figure-note">
            시스템이 제시하는 분류와 서류는 검토 후보이며, 최종 판단은 관세 당국 또는
            자격을 갖춘 전문가의 확인이 필요합니다.
          </p>
        </section>
      </div>
    </section>
  );
}

export default function IntroductionPage() {
  return (
    <main className="introduction-page">
      <IntroductionHero />
    </main>
  );
}
