import { useState } from "react";
import { CircleHelp } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export default function UserQuestionPanel({
  questions,
  onSubmit,
  submitting = false,
  error = "",
}) {
  const [answers, setAnswers] = useState({});
  const selected = questions
    .filter((question) => answers[question.user_question_id])
    .map((question) => ({
      user_question_id: question.user_question_id,
      answer: answers[question.user_question_id],
    }));

  return (
    <Card className="border-warning/50 bg-warning/5">
      <CardHeader>
        <div className="flex items-center gap-2">
          <CircleHelp className="size-5 text-warning" aria-hidden="true" />
          <CardTitle>분류 조건 확인</CardTitle>
          <Badge variant="outline">{questions.length}개 질문</Badge>
        </div>
        <CardDescription>
          답변이 필요한 지점에서 분류가 정지했습니다. 확인 가능한 항목에 답하면 이어서 실행합니다.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        {questions.map((question, index) => {
          const questionId = question.user_question_id;
          const selectedAnswer = answers[questionId];
          return (
            <fieldset className="grid gap-3 rounded-lg border bg-surface p-4" key={questionId}>
              <legend className="sr-only">분류 질문 {index + 1}</legend>
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <Badge variant="secondary">{String(question.stage || "분류").toUpperCase()}</Badge>
                {question.candidate_code ? <span>후보 {question.candidate_code}</span> : null}
              </div>
              <p className="m-0 text-sm font-medium leading-6 text-foreground">
                {question.question_text}
              </p>
              <div className="flex gap-2" role="group" aria-label={`질문 ${index + 1} 답변`}>
                <Button
                  type="button"
                  variant={selectedAnswer === "yes" ? "default" : "outline"}
                  aria-pressed={selectedAnswer === "yes"}
                  disabled={submitting}
                  onClick={() => setAnswers((current) => ({ ...current, [questionId]: "yes" }))}
                >
                  예
                </Button>
                <Button
                  type="button"
                  variant={selectedAnswer === "no" ? "default" : "outline"}
                  aria-pressed={selectedAnswer === "no"}
                  disabled={submitting}
                  onClick={() => setAnswers((current) => ({ ...current, [questionId]: "no" }))}
                >
                  아니오
                </Button>
              </div>
            </fieldset>
          );
        })}
        {error ? <p className="m-0 text-sm text-destructive" role="alert">{error}</p> : null}
        <div className="flex justify-end">
          <Button
            type="button"
            disabled={submitting || !selected.length}
            onClick={() => onSubmit(selected)}
          >
            {submitting ? "분류 재개 중" : "선택한 답변으로 계속"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
