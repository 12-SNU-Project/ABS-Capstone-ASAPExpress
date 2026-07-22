import DataTable from "@/components/DataTable";
import { RoutingScoreLabel, RoutingTermLabel } from "@/lib/labels.js";
import { asList, asObject, clean } from "@/lib/format.js";
import { EvidenceTerms, FactLabel } from "./EvidenceElements";

export default function TariffRoutingPanel({ result }) {
  const routingView = asObject(result?.routing_view);
  const understandingView = asObject(result?.product_understanding_view);
  const hints = asObject(understandingView.identity_hints);
  const chapterDetails = asList(routingView.candidate_chapter_details).map((detail) => {
    const source = asObject(detail);
    const scoreBreakdown = Object.entries(asObject(source.score_breakdown)).flatMap(
      ([key, amount]) => {
        const score = Number(amount);
        return Number.isFinite(score) && score !== 0
          ? [`${RoutingScoreLabel(key)} ${score > 0 ? "+" : ""}${score}`]
          : [];
      },
    );
    return {
      chapter: clean(source.chapter),
      score: source.score,
      scoreBreakdown: scoreBreakdown.length ? scoreBreakdown : ["세부 점수 기록 없음"],
      rawEvidence: asList(source.matched_terms).length
        ? asList(source.matched_terms).slice(0, 4).map(RoutingTermLabel)
        : ["기록된 어휘 없음"],
    };
  });
  const missingFacts = asList(routingView.missing_facts).map(FactLabel);
  const topChapter = chapterDetails[0];
  const scoredChapters = chapterDetails.filter((detail) => Number(detail.score) > 0).slice(0, 5);
  const comparedChapters = scoredChapters.length ? scoredChapters : chapterDetails.slice(0, 5);

  return (
    <div className="cjs-panel cjs-routing-panel">
      <div className="cjs-panel-title">챕터 후보 좁히기</div>
      {chapterDetails.length ? (
        <>
          <div className="cjs-routing-summary">
            <div className="cjs-routing-primary-result">
              <span>현재 1순위 후보</span>
              <div><small>HS2</small><strong>{topChapter.chapter}</strong></div>
            </div>
            <div className="cjs-routing-score-result">
              <span>상대 점수</span>
              <strong>{topChapter.score}</strong>
              <small>확률이나 신뢰도가 아닌 후보 비교값</small>
            </div>
          </div>

          {missingFacts.length ? (
            <div className="cjs-routing-warning">
              <strong>추가 확인</strong>
              <span>{missingFacts.join(", ")} 정보가 있으면 후보 비교를 더 정교하게 검토할 수 있습니다.</span>
            </div>
          ) : null}

          <div className="cjs-routing-section-heading">
            <strong>{scoredChapters.length ? "점수를 받은 후보" : "비교 후보"}</strong>
            <span>같은 실행 안에서 상위 5개까지 비교합니다.</span>
          </div>
          <DataTable
            rows={comparedChapters}
            limit={5}
            className="cjs-routing-table"
            columns={[
              { key: "chapter", label: "HS2 챕터", variant: "mono" },
              { key: "score", label: "상대 점수", variant: "mono" },
              { key: "scoreBreakdown", label: "점수 구성", variant: "chips" },
            ]}
          />

          <details className="cjs-secondary-evidence cjs-routing-details">
            <summary>사전 힌트와 전체 후보 근거 보기</summary>
            <div className="cjs-subpanel-title cjs-first">상품 이해에서 전달된 사전 힌트</div>
            {clean(hints.chapter_hint_basis) ? (
              <p className="cjs-desc-text">{clean(hints.chapter_hint_basis)}</p>
            ) : (
              <div className="cjs-muted">기록된 챕터 사전 힌트가 없습니다.</div>
            )}
            <EvidenceTerms label="챕터 힌트" terms={hints.chapter_hint_terms} />
            <EvidenceTerms label="챕터 기준 어휘" terms={hints.chapter_hint_source_terms} />
            <EvidenceTerms label="라우팅 어휘" terms={understandingView.routing_terms} />

            <div className="cjs-subpanel-title">후보별 원문 근거</div>
            <DataTable
              rows={chapterDetails}
              limit={chapterDetails.length}
              className="cjs-routing-detail-table"
              columns={[
                { key: "chapter", label: "HS2 챕터", variant: "mono" },
                { key: "score", label: "상대 점수", variant: "mono" },
                { key: "rawEvidence", label: "라우팅에서 확인한 어휘", variant: "chips" },
              ]}
            />

            <div className="cjs-subpanel-title">전체 라우팅 검토 범위</div>
            <EvidenceTerms label="라우팅 검토 범위" terms={routingView.allowed_hs2} />
            <EvidenceTerms label="검토 도메인" terms={routingView.domain_scopes} />
          </details>
        </>
      ) : (
        <div className="cjs-muted">기록된 HS2 후보가 없습니다.</div>
      )}
    </div>
  );
}
