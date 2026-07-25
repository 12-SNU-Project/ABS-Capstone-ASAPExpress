import assert from "node:assert/strict";
import test from "node:test";
import {
  CreateRunLifecycle,
  IsCurrentRunOperation,
  PrepareRunSnapshot,
  ShouldConnectRunSnapshot,
  ShouldPrepareRunTransition,
} from "./useClassificationRun.js";

function CreateEventSourceStub() {
  return {
    closeCount: 0,
    close() {
      this.closeCount += 1;
    },
  };
}

test("늦게 도착한 이전 작업 응답은 현재 작업으로 인정하지 않는다", () => {
  assert.equal(IsCurrentRunOperation(2, 1), false);
  assert.equal(IsCurrentRunOperation(2, 2), true);
});

test("잘못된 작업 복원 실패는 기존 실행과 EventSource를 유지한다", async () => {
  const lifecycle = CreateRunLifecycle();
  const currentJobId = "job-current";
  const activeOperation = lifecycle.BeginActiveOperation();
  const source = CreateEventSourceStub();
  lifecycle.AttachEventSource(source);

  const preparation = await PrepareRunSnapshot(
    "job-missing",
    lifecycle,
    async () => { throw new Error("404"); },
  );

  assert.equal(preparation.status, "failed");
  assert.equal(currentJobId, "job-current");
  assert.equal(source.closeCount, 0);
  assert.equal(lifecycle.IsCurrentEventSource(source, activeOperation), true);
});

test("복원 준비가 실패해도 기존 EventSource는 종료되지 않는다", () => {
  const lifecycle = CreateRunLifecycle();
  const activeOperation = lifecycle.BeginActiveOperation();
  const source = CreateEventSourceStub();
  lifecycle.AttachEventSource(source);

  lifecycle.BeginRestoreOperation();

  assert.equal(source.closeCount, 0);
  assert.equal(lifecycle.IsCurrentEventSource(source, activeOperation), true);
});

test("복원 성공 commit은 기존 EventSource를 정확히 한 번 종료한다", async () => {
  const lifecycle = CreateRunLifecycle();
  lifecycle.BeginActiveOperation();
  const source = CreateEventSourceStub();
  lifecycle.AttachEventSource(source);
  const preparation = await PrepareRunSnapshot(
    "job-next",
    lifecycle,
    async () => ({ job_id: "job-next", job_status: "completed" }),
  );

  const nextOperation = lifecycle.CommitRestoreOperation(preparation.restoreOperation);

  assert.equal(preparation.status, "ready");
  assert.ok(nextOperation);
  assert.equal(source.closeCount, 1);
  lifecycle.CloseEventSource();
  assert.equal(source.closeCount, 1);
});

test("실행 중인 복원 snapshot에는 새 EventSource를 연결할 수 있다", async () => {
  const lifecycle = CreateRunLifecycle();
  const preparation = await PrepareRunSnapshot(
    "job-running",
    lifecycle,
    async () => ({ job_id: "job-running", job_status: "running" }),
  );
  const nextOperation = lifecycle.CommitRestoreOperation(preparation.restoreOperation);
  const nextSource = CreateEventSourceStub();

  assert.equal(ShouldConnectRunSnapshot(preparation.snapshot), true);
  assert.equal(ShouldConnectRunSnapshot({ job_status: "completed" }), false);
  assert.equal(ShouldConnectRunSnapshot({ job_status: "awaiting_input" }), false);
  lifecycle.AttachEventSource(nextSource);

  assert.equal(lifecycle.IsCurrentEventSource(nextSource, nextOperation), true);
});

test("같은 작업 번호는 전환하지 않아 중복 SSE를 만들지 않는다", () => {
  assert.equal(ShouldPrepareRunTransition("job-1", "job-1"), false);
  assert.equal(ShouldPrepareRunTransition(" job-1 ", "job-1"), false);
});

test("연속 복원 요청은 마지막 snapshot만 commit한다", async () => {
  const lifecycle = CreateRunLifecycle();
  let resolveFirst;
  let resolveSecond;
  const first = PrepareRunSnapshot("job-a", lifecycle, () => new Promise((resolve) => {
    resolveFirst = resolve;
  }));
  const second = PrepareRunSnapshot("job-b", lifecycle, () => new Promise((resolve) => {
    resolveSecond = resolve;
  }));
  resolveFirst({ job_id: "job-a" });
  resolveSecond({ job_id: "job-b" });
  const [firstResult, secondResult] = await Promise.all([first, second]);

  assert.equal(firstResult.restoreOperation.signal.aborted, true);
  assert.equal(firstResult.status, "stale");
  assert.equal(lifecycle.CommitRestoreOperation(firstResult.restoreOperation), null);
  assert.equal(secondResult.status, "ready");
  assert.ok(lifecycle.CommitRestoreOperation(secondResult.restoreOperation));
});

test("늦게 도착한 이전 복원 응답은 현재 실행을 덮어쓰지 않는다", () => {
  const lifecycle = CreateRunLifecycle();
  const first = lifecycle.BeginRestoreOperation();
  const second = lifecycle.BeginRestoreOperation();

  assert.equal(lifecycle.IsCurrentRestoreOperation(first), false);
  assert.equal(lifecycle.IsCurrentRestoreOperation(second), true);
});
