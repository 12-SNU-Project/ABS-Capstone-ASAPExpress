import { useEffect, useRef, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { GetNextStoryIndex } from "./heroStoryModel";

const STAGES = [
  {
    id: "route",
    index: "01",
    label: "Route",
    title: "한국에서 유럽 시장까지",
    summary: "수출 시나리오의 출발지와 도착 규제 시장을 먼저 구분합니다.",
  },
  {
    id: "collect",
    index: "02",
    label: "Collect",
    title: "상품 근거를 구조화",
    summary: "페이지와 이미지에서 분류에 필요한 상품 사실을 복원합니다.",
  },
  {
    id: "classify",
    index: "03",
    label: "Classify",
    title: "근거에 따라 후보를 좁히기",
    summary: "포함·제외 조건을 비교하며 HS에서 TARIC 후보까지 계층을 확장합니다.",
  },
  {
    id: "documents",
    index: "04",
    label: "Documents",
    title: "조건에 맞는 서류 검토",
    summary: "선택 후보와 수출 조건을 기준으로 준비 서류의 우선순위를 구분합니다.",
  },
];

function TradeRouteVisual({ active, reduceMotion }) {
  const routeRef = useRef(null);
  const planeRef = useRef(null);

  useEffect(() => {
    const route = routeRef.current;
    const plane = planeRef.current;
    if (!route || !plane) return undefined;

    const routeLength = route.getTotalLength();
    const SetProgress = (progress) => {
      const distance = routeLength * progress;
      const point = route.getPointAtLength(distance);
      const tangentPoint = route.getPointAtLength(Math.min(distance + 1, routeLength));
      const angle = Math.atan2(tangentPoint.y - point.y, tangentPoint.x - point.x) * (180 / Math.PI);
      plane.setAttribute("transform", `translate(${point.x} ${point.y}) rotate(${angle})`);
      route.style.strokeDasharray = `${routeLength}`;
      route.style.strokeDashoffset = `${routeLength * (1 - progress)}`;
    };

    if (!active || reduceMotion) {
      SetProgress(1);
      return undefined;
    }

    let frame;
    let startTime;
    SetProgress(0);
    const AnimatePlane = (time) => {
      if (!startTime) startTime = time;
      const progress = Math.min((time - startTime) / 4200, 1);
      SetProgress(1 - ((1 - progress) ** 3));
      if (progress < 1) frame = requestAnimationFrame(AnimatePlane);
    };
    frame = requestAnimationFrame(AnimatePlane);
    return () => cancelAnimationFrame(frame);
  }, [active, reduceMotion]);

  return (
    <svg className="introduction-route-map" viewBox="0 0 620 250" role="img" aria-label="대한민국에서 유럽으로 이어지는 수출 경로">
      <g className="introduction-map-land" aria-hidden="true">
        <path d="M37 78 76 45l71-5 50 19 36-10 38 35-20 30-47 3-18 28-61-8-34 17-53-24-1-52Z" />
        <path d="m309 53 49-27 83 9 48 29 65 8 22 35-26 33-61-5-35 24-56-11-43 12-49-29 20-36-17-42Z" />
        <path d="m430 165 61-14 51 24-11 38-51 14-43-22-7-40Z" />
      </g>
      <path className="introduction-route-line-base" d="M520 105 C412 37 260 53 116 164" aria-hidden="true" />
      <path ref={routeRef} className="introduction-route-line-active" d="M520 105 C412 37 260 53 116 164" aria-hidden="true" />
      <g className="introduction-route-marker" aria-hidden="true">
        <circle cx="520" cy="105" r="11" /><circle cx="520" cy="105" r="3.5" />
        <circle cx="116" cy="164" r="11" /><circle cx="116" cy="164" r="3.5" />
      </g>
      <g ref={planeRef} className="introduction-route-plane" aria-hidden="true">
        <path d="M-13-5 1-2 8-11l4 1-4 10 11 3v4L8 6l4 10-4 1-7-9-14 4-4-3 10-6-10-5 4-3Z" />
      </g>
      <text x="498" y="134">KOREA</text>
      <text x="88" y="194">EUROPE</text>
      <g className="introduction-route-ledger" aria-hidden="true">
        <line x1="42" y1="226" x2="578" y2="226" />
        <text x="42" y="244">EXPORTER</text>
        <text x="236" y="244">ORIGIN EVIDENCE</text>
        <text x="472" y="244">EU DESTINATION</text>
      </g>
    </svg>
  );
}

function ProductCollectionVisual({ active }) {
  return (
    <div className={`introduction-evidence-flow${active ? " is-active" : ""}`} aria-hidden="true">
      <div className="introduction-source-block">
        <span>01 · SOURCE</span>
        <strong>상품 페이지 URL</strong>
        <small>웹 문서 · 상품 이미지</small>
      </div>
      <span className="introduction-flow-arrow">→</span>
      <div className="introduction-evidence-samples">
        <span className="introduction-sample-image">상품</span>
        <span className="introduction-sample-image">표</span>
        <span className="introduction-sample-image">라벨</span>
        <small><i /> VLM / OCR 처리</small>
      </div>
      <span className="introduction-flow-arrow">→</span>
      <dl className="introduction-fact-ledger">
        <div><dt>상품 유형</dt><dd>냉동 가공식품</dd></div>
        <div><dt>주요 성분</dt><dd>주재료 · 부재료</dd></div>
        <div><dt>표시 중량</dt><dd>정규화된 값</dd></div>
        <div><dt>검토 상태</dt><dd>근거 연결 완료</dd></div>
      </dl>
    </div>
  );
}

function ClassificationVisual({ active }) {
  return (
    <div className={`introduction-decision-tree${active ? " is-active" : ""}`} aria-hidden="true">
      <div className="introduction-evidence-column">
        <span>PRODUCT EVIDENCE</span>
        <ul>
          <li>주재료 구성</li>
          <li>가공 상태</li>
          <li>보존 방식</li>
          <li>상품 용도</li>
        </ul>
      </div>

      <div className="introduction-tree-node introduction-tree-root">
        <span>HS2</span>
        <strong>류 후보군</strong>
      </div>

      <div className="introduction-branch-column">
        <div className="introduction-tree-node is-rejected">
          <span>HS4 · 후보 A</span>
          <strong>제외</strong>
          <small>재료 조건 불일치</small>
        </div>
        <div className="introduction-tree-node is-selected">
          <span>HS4 · 후보 B</span>
          <strong>선택 경로</strong>
          <small>포함 조건 일치</small>
        </div>
        <div className="introduction-tree-node is-review">
          <span>HS4 · 후보 C</span>
          <strong>보류</strong>
          <small>용도 추가 확인</small>
        </div>
      </div>

      <div className="introduction-depth-chain">
        <div className="introduction-tree-node">
          <span>HS6</span>
          <strong>소호 후보</strong>
        </div>
        <div className="introduction-tree-node">
          <span>CN8</span>
          <strong>EU 세분류</strong>
        </div>
        <div className="introduction-tree-node is-final">
          <span>TARIC10</span>
          <strong>검토 후보</strong>
          <small>전문가 확인 필요</small>
        </div>
      </div>
    </div>
  );
}

function DocumentGuidanceVisual({ active }) {
  return (
    <div className={`introduction-document-flow${active ? " is-active" : ""}`} aria-hidden="true">
      <div className="introduction-document-context">
        <span>CLASSIFICATION CONTEXT</span>
        <dl>
          <div><dt>분류 기준</dt><dd>TARIC 후보</dd></div>
          <div><dt>원산지</dt><dd>증빙 상태 확인</dd></div>
          <div><dt>상품 조건</dt><dd>용도·성분 검토</dd></div>
        </dl>
      </div>
      <span className="introduction-flow-arrow">→</span>
      <div className="introduction-document-ledger">
        <p><span>REQUIRED</span><strong>Commercial Invoice</strong><small>기본 준비</small></p>
        <p><span>REQUIRED</span><strong>Packing List</strong><small>기본 준비</small></p>
        <p><span>CONDITIONAL</span><strong>Certificate of Origin</strong><small>원산지 조건</small></p>
        <p><span>REVIEW</span><strong>Official Certificate</strong><small>품목별 확인</small></p>
      </div>
    </div>
  );
}

function StageVisual({ stage, active, reduceMotion }) {
  if (stage === "route") {
    return <TradeRouteVisual active={active} reduceMotion={reduceMotion} />;
  }
  if (stage === "collect") {
    return <ProductCollectionVisual active={active} />;
  }
  if (stage === "classify") {
    return <ClassificationVisual active={active} />;
  }
  return <DocumentGuidanceVisual active={active} />;
}

export default function HeroStorySequence() {
  const rootRef = useRef(null);
  const reduceMotion = useReducedMotion();
  const [activeIndex, setActiveIndex] = useState(0);
  const [pageVisible, setPageVisible] = useState(document.visibilityState === "visible");
  const [inView, setInView] = useState(true);

  useEffect(() => {
    const root = rootRef.current;
    if (!root || typeof IntersectionObserver === "undefined") return undefined;
    const observer = new IntersectionObserver(([entry]) => setInView(entry.isIntersecting), {
      threshold: 0.15,
    });
    observer.observe(root);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const HandleVisibility = () => setPageVisible(document.visibilityState === "visible");
    document.addEventListener("visibilitychange", HandleVisibility);
    return () => document.removeEventListener("visibilitychange", HandleVisibility);
  }, []);

  useEffect(() => {
    if (reduceMotion || !pageVisible || !inView) return undefined;
    const timer = window.setTimeout(() => {
      setActiveIndex((index) => GetNextStoryIndex(index, STAGES.length));
    }, 5500);
    return () => clearTimeout(timer);
  }, [activeIndex, inView, pageVisible, reduceMotion]);

  return (
    <div
      ref={rootRef}
      className="introduction-story"
      role="region"
      aria-label="ASAP Express 수출 분석 흐름"
    >
      <ol className="introduction-stage-index" aria-label="자동으로 전개되는 분석 단계">
        {STAGES.map((stage, index) => (
          <li
            className={index === activeIndex ? "is-active" : ""}
            key={stage.id}
            aria-current={index === activeIndex ? "step" : undefined}
          >
            <span>{stage.index}</span>
            <strong>{stage.label}</strong>
          </li>
        ))}
      </ol>

      <div className="introduction-stage-canvas">
        {STAGES.map((stage, index) => {
          const active = index === activeIndex;
          return (
            <motion.section
              className={`introduction-stage-view${active ? " is-active" : ""}`}
              key={stage.id}
              initial={false}
              animate={{ opacity: active ? 1 : 0 }}
              transition={{ duration: reduceMotion ? 0 : 0.28, ease: "easeOut" }}
              aria-hidden={!active}
            >
              <header className="introduction-stage-caption">
                <p>{stage.index} / 04</p>
                <div>
                  <h2>{stage.title}</h2>
                  <p>{stage.summary}</p>
                </div>
              </header>
              <StageVisual
                stage={stage.id}
                active={active && pageVisible && inView}
                reduceMotion={reduceMotion}
              />
            </motion.section>
          );
        })}
      </div>
    </div>
  );
}
