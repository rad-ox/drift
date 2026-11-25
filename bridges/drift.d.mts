// TypeScript declarations for the zero-dependency DRIFT JS/TS bridge (drift.mjs).

export type DriftCheckValue = unknown | ((expected: unknown, sample?: Record<string, unknown>) => unknown | Promise<unknown>);

export interface DriftMutationTarget {
  contract: string;
  case: string;
  path: string;
  after?: unknown;
  isWhen?: boolean;
  segments?: string[] | null;
}

export interface DriftObserveRecord {
  contract?: string;
  case?: string;
  test?: string;
  at?: string[];
  when?: Record<string, unknown>;
  then: Record<string, unknown>;
}

export interface RunDriftCaseOptions {
  contract: string;
  test?: string;
  t?: unknown;
  project?: string;
  strictWhen?: boolean;
  cases: readonly string[];
  level?: string;
}

export declare class DriftContext {
  readonly contractId: string;
  readonly testId: string;
  readonly cases: string[];
  readonly level: string;
  readonly view: Record<string, unknown>;
  readonly reads: Map<string, Set<string>>;
  readonly whenReads: Map<string, Set<string>>;
  readonly inputFiles: Map<string, string>;
  readonly obs: Record<string, unknown>;

  when(caseId: string, key: string): unknown;
  findWhen<T = unknown>(caseId: string, key: string, fallback?: T): unknown;
  whenTable(caseId: string): Record<string, unknown>;
  unreadWhen(caseId: string): string[];
  forEachCase(fn: (caseId: string, when: Record<string, unknown>) => unknown | Promise<unknown>): Promise<void>;

  expect(caseId: string, key: string): unknown;
  findThen<T = unknown>(caseId: string, key: string, fallback?: T): unknown;
  then(caseId: string): Record<string, unknown>;

  recordInput(filePath: string, pre?: Buffer | Uint8Array | string | null): string;
  readFixture(filePath: string, encoding?: BufferEncoding | null): string | Buffer;
  bindUiEnvironment(profile: unknown, options?: unknown): unknown;

  check(caseId: string, checks: Record<string, DriftCheckValue>, when?: Record<string, unknown> | null): Promise<void>;
  checkBounds(caseId: string, domain: Record<string, unknown>, checks: Record<string, DriftCheckValue>): Promise<void>;
  profileDomain(param: string | readonly string[]): Record<string, unknown>[];
  checkProfileBounds(caseId: string, param: string | readonly string[], checks: Record<string, DriftCheckValue>): Promise<void>;
  buildInput(caseId: string, base?: Record<string, unknown>): Record<string, unknown>;
  buildOutput(caseId: string, base?: Record<string, unknown>): Record<string, unknown>;
  checkProjection(caseId: string, payload: unknown, checks?: Record<string, DriftCheckValue>, when?: Record<string, unknown> | null): Promise<void>;
  checkAdverse(caseId: string, harness: unknown, checks?: Record<string, DriftCheckValue>): Promise<void>;
  checkSeamBounds(caseId: string, idOrRes: string, prodCase: string, checks: Record<string, DriftCheckValue>, base?: Record<string, unknown>): Promise<void>;
  checkFrame(caseId: string, frameObs: unknown): void;
  checkIdempotency(caseId: string, obs: unknown): Promise<void>;
  checkSeamProbe(caseId: string, obs: unknown): void;
  checkRollback(caseId: string, obs: unknown): void;
  checkLogSink(caseId: string, obs: unknown): void;
  checkView(caseId: string, view: unknown, checks?: Record<string, DriftCheckValue>, when?: Record<string, unknown> | null): Promise<void>;
  fullyReadCases(): string[];
}

export declare function runDriftCase(
  options: RunDriftCaseOptions,
  fn: (ctx: DriftContext) => unknown | Promise<unknown>
): Promise<'passed' | 'skipped-by-select'>;

export declare function shouldRun(contractId: string, testId: string, cases?: readonly string[]): boolean;
export declare function resetDriftCache(): void;
export declare function selectFiles(sel?: string | Record<string, unknown>, rootDir?: string): string[];
export declare function testIdOf(t: unknown): string;
export declare function buildStub(idOrRes: string, caseId: string, base?: Record<string, unknown>): Record<string, unknown>;
export declare function buildStubVariants(idOrRes: string, caseId: string, base?: Record<string, unknown>): Record<string, unknown>[];
export declare function verifyStub(idOrRes: string, caseId: string, payload: unknown): boolean;
export declare function withMutation<T>(target: DriftMutationTarget, fn: () => T | Promise<T>): Promise<T>;
export declare function mutationDepth(): number;
export declare function observe(rec: DriftObserveRecord): boolean;

export declare function bindUiEnvironment(...args: unknown[]): unknown;
export declare function captureSurfaceView(...args: unknown[]): unknown;
export declare function checkViewTable(...args: unknown[]): Promise<void>;
export declare function collectPlaywrightSequence(...args: unknown[]): Promise<unknown>;
export declare function collectUiSequence(...args: unknown[]): Promise<unknown>;
export declare function evaluateScenarioMatrix(...args: unknown[]): unknown;
export declare function evaluateTaskRecovery(...args: unknown[]): unknown;
export declare function expandDomain(domain: Record<string, unknown>, mutated?: boolean): Record<string, unknown>[];
export declare function observeUiSequence(...args: unknown[]): unknown;
