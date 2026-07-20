import { useEffect, useState } from "react";
import { extractTrace, fetchBlackboard } from "../lib/traceContract.js";

// 런 완료 후 blackboard를 1회 로드해 trace 계약 뷰모델로 돌려준다.
export function useBlackboardTrace(jobId, ready = true) {
  const [trace, setTrace] = useState(null);
  useEffect(() => {
    let alive = true;
    if (!jobId || !ready) {
      setTrace(null);
      return undefined;
    }
    fetchBlackboard(jobId).then((board) => {
      if (alive) {
        setTrace(board ? extractTrace(board) : null);
      }
    });
    return () => {
      alive = false;
    };
  }, [jobId, ready]);
  return trace;
}
