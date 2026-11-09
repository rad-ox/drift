// DRIFT extension for Pi (@earendil-works/pi-coding-agent).
// Injects DRIFT context and checks alignment (one correction per user prompt).
// Recovers an errored prompt once after host compaction, never after cancellation.
// Resolves native drift (Linux/WSL/macOS) vs drift.exe (Windows).
import { execFile, execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { truncateToWidth, visibleWidth } from "@earendil-works/pi-tui";

// Set only in installer-rendered copies, never in source-linked extensions.
const releaseDirectory = "";

interface ReleaseContext {
  cwd?: string;
  ui?: { notify?: (message: string, level: "info" | "warning") => void };
}

export function registerSessionReleaseNotice(
  pi: { on: (event: "session_start", handler: (event: unknown, ctx: ReleaseContext) => Promise<void>) => void },
  getArea: (cwd: string) => string | null,
  getBin: () => string | null,
) {
  pi.on("session_start", async (_event, ctx) => {
    if (!releaseDirectory || process.env.DRIFT_UPDATE_CHECK === "0" ||
        !existsSync(releaseDirectory) || !getArea(ctx.cwd || process.cwd())) return;
    const bin = getBin();
    if (!bin) return;
    const windows = process.platform === "win32";
    const command = windows ? "powershell.exe" : "python3";
    const args = windows
      ? ["-NoProfile", "-NonInteractive", "-File", join(releaseDirectory, "check.ps1"), "-DriftExe", bin]
      : [join(releaseDirectory, "check.py"), bin];
    await new Promise<void>((done) => {
      execFile(command, args, { timeout: 3000, maxBuffer: 4096, encoding: "utf8" },
        (error, stdout, stderr) => {
          const warning = stderr.trim() || (error
            ? "drift: release check unavailable; continuing without an update verdict." : "");
          const message = warning || stdout.trim();
          if (message) {
            if (ctx.ui?.notify) ctx.ui.notify(message, warning ? "warning" : "info");
            else console.warn(message);
          }
          done();
        });
    });
  });
}

interface RecoveryEvent {
  messageType?: unknown;
  reason?: unknown;
  willRetry?: unknown;
  outcome?: unknown;
  branchEntries?: { id?: unknown }[];
  compactionEntry?: { parentId?: unknown };
  context?: { canContinue?: unknown };
}

interface RecoveryContext {
  cwd?: string;
  ui?: { notify?: (message: string, level: "warning") => void };
}

export function createCompactionRecovery(isActive: (ctx: RecoveryContext) => boolean) {
  let epoch = 0;
  let active = false;
  let recovered = false;
  let pending: { epoch: number; parent: string } | null = null;
  let ready = false;

  return {
    sessionStart() {
      epoch++;
      active = false;
      recovered = false;
      pending = null;
      ready = false;
    },
    beforeStart(event: RecoveryEvent, ctx: RecoveryContext) {
      if (event.messageType !== "user") return;
      epoch++;
      active = isActive(ctx);
      recovered = false;
      pending = null;
      ready = false;
    },
    beforeCompact(event: RecoveryEvent) {
      ready = false;
      pending = null;
      const parent = event.branchEntries?.at(-1)?.id;
      if (active && event.reason === "threshold" && event.willRetry === false &&
          typeof parent === "string" && parent.length > 0) {
        pending = { epoch, parent };
      }
    },
    compacted(event: RecoveryEvent) {
      if (pending?.epoch === epoch && event.reason === "threshold" &&
          event.willRetry === false && event.compactionEntry?.parentId === pending.parent) {
        ready = true;
      }
    },
    failed() {
      pending = null;
      ready = false;
    },
    settled() {
      active = false;
      pending = null;
      ready = false;
    },
    beforeSettle(event: RecoveryEvent, ctx: RecoveryContext): { continue: true } | undefined {
      if (event.outcome === "completed" || event.outcome === "aborted") {
        ready = false;
        pending = null;
        return;
      }
      if (!active || !isActive(ctx) || event.outcome !== "error" || !ready || recovered) return;
      recovered = true;
      ready = false;
      pending = null;
      if (event.context?.canContinue !== true) {
        const message = "Pi cannot continue this turn after compaction; resume it explicitly.";
        if (typeof ctx.ui?.notify === "function") ctx.ui.notify(message, "warning");
        else console.warn(message);
        return;
      }
      return { continue: true };
    },
  };
}

function findDriftArea(startCwd: string): string | null {
  let cur = resolve(startCwd || process.cwd());
  while (cur) {
    if (existsSync(join(cur, ".drift", "config.toml"))) {
      return cur;
    }
    if (existsSync(join(cur, ".git"))) {
      break;
    }
    const parent = dirname(cur);
    if (!parent || parent === cur) {
      break;
    }
    cur = parent;
  }
  return null;
}

function resolveDriftBinary(): string | null {
  const isWin = process.platform === "win32";
  const home = homedir();
  const localAppData = process.env.LOCALAPPDATA || join(home, "AppData", "Local");
  const candidates = isWin
    ? [
        process.env.DRIFT_CLI || "",
        join(localAppData, "Programs", "drift", "bin", "drift.exe"),
        "drift.exe",
      ]
    : [
        process.env.DRIFT_CLI || "",
        join(home, ".local", "bin", "drift"),
        "drift",
      ];
  for (const cand of candidates) {
    if (!cand) continue;
    if (cand.includes("/") || cand.includes("\\")) {
      if (existsSync(cand)) return cand;
    } else {
      return cand;
    }
  }
  return null;
}

// Pi settles once per user prompt; the classified message states that task
// relevance is unknown because no trusted task attribution exists.
export function describeCheckFailure(err: any, driftDir: string): string {
  const status = typeof err?.status === "number" ? err.status : null;
  const stdout = String(err?.stdout ?? "");
  if (status === 1) {
    try {
      const report = JSON.parse(stdout);
      const files: any[] = Array.isArray(report?.files) ? report.files : [];
      const all = files.flatMap((f) => (Array.isArray(f?.findings) ? f.findings.map((x: any) => ({ file: String(f?.file ?? ""), ...x })) : []));
      const first = all[0] ?? {};
      const where = first.path ? ` (${first.path})` : "";
      return `DRIFT area check found ${all.length} finding(s) in ${driftDir}; relevance to the current task is unknown (no trusted task attribution). First: ${first.file ?? ""}${where}: ${first.code ?? ""} ${first.message ?? ""}. Next: if this task changed that file, run drift explain ${first.code ?? ""} and fix it; otherwise report it without editing unrelated contracts. The full-area check remains required before delivery.`;
    } catch {
      // Fall through: an unparseable report is an input or tooling failure.
    }
  }
  const lines = `${String(err?.stderr ?? "")}\n${stdout}\n${String(err?.message ?? "")}`.split(/\r?\n/u);
  const cause = (lines.find((l) => l.trim()) ?? "no diagnostic").trim().slice(0, 200);
  const exit = status ?? (err?.signal ? `signal ${err.signal}` : String(err?.code ?? "spawn"));
  return `DRIFT area check could not run in ${driftDir} (exit ${exit}: invocation, input or environment): ${cause}. Next: run drift check ${driftDir} to inspect the tooling or input error; formatting contracts will not fix it. No check verdict is available.`;
}

export default function (pi: any) {
  let settledForCurrentPrompt = false;
  let footerInstalled = false;
  let lastUnownedKey = "";
  let cachedBin: string | null | undefined;
  let cachedCwd = "";
  let cachedArea: string | null = null;
  let cachedStatusCwd = "";
  let cachedStatusAt = 0;
  let cachedStatusBadge = "";
  let cachedSessionId = "";
  let cachedLeafId: string | null = null;
  let cachedEntryCount = -1;
  let cachedUsage: {
    input: number;
    output: number;
    cacheRead: number;
    cacheWrite: number;
    cost: number;
    latestCacheHitRate?: number;
  } | null = null;
  const recovery = createCompactionRecovery(
    (ctx) => getArea(ctx.cwd || process.cwd()) !== null,
  );
  registerSessionReleaseNotice(pi, getArea, getBin);

  function getArea(cwd: string): string | null {
    if (cwd === cachedCwd && cachedArea && existsSync(join(cachedArea, ".drift", "config.toml"))) {
      return cachedArea;
    }
    cachedCwd = cwd;
    cachedArea = findDriftArea(cwd);
    return cachedArea;
  }

  function getBin(): string | null {
    if (cachedBin === undefined) {
      cachedBin = resolveDriftBinary();
    }
    return cachedBin;
  }

  function formatTokens(count: number): string {
    if (count < 1000) return `${count}`;
    if (count < 10000) return `${(count / 1000).toFixed(1)}k`;
    if (count < 1000000) return `${Math.round(count / 1000)}k`;
    if (count < 10000000) return `${(count / 1000000).toFixed(1)}M`;
    return `${Math.round(count / 1000000)}M`;
  }

  function formatCwd(cwd: string): string {
    const home = process.env.HOME || process.env.USERPROFILE;
    if (!home) return cwd;
    const resolvedCwd = resolve(cwd);
    const resolvedHome = resolve(home);
    const rel = relative(resolvedHome, resolvedCwd);
    const inside = rel === "" || (rel !== ".." && !rel.startsWith(`..${sep}`) && !isAbsolute(rel));
    if (!inside) return cwd;
    return rel === "" ? "~" : `~${sep}${rel}`;
  }

  function getDriftStatusBadge(cwd: string, theme: any): string {
    const area = getArea(cwd);
    if (!area) return "";
    const now = Date.now();
    if (cwd === cachedStatusCwd && now - cachedStatusAt < 4000) {
      return cachedStatusBadge;
    }
    cachedStatusCwd = cwd;
    cachedStatusAt = now;
    const bin = getBin();
    const contractsDir = join(area, ".drift", "contracts");
    if (!bin || !existsSync(contractsDir)) {
      cachedStatusBadge = "";
      return "";
    }
    try {
      const out = execFileSync(bin, ["status", contractsDir], {
        cwd: area,
        encoding: "utf-8",
        timeout: 1500,
        stdio: ["ignore", "pipe", "ignore"],
      });
      const m = /(\d+)\/(\d+)\s+current(?:,\s*(\d+)\s+stale)?(?:,\s*(\d+)\s+blocked)?(?:,\s*(\d+)\s+absent)?(?:,\s*(\d+)\s+open)?\s*(?:\((\d+)\s+cases\))?/u.exec(
        out,
      );
      if (m) {
        const cur = Number(m[1] || 0);
        const tot = Number(m[2] || 0);
        const stale = Number(m[3] || 0);
        const blocked = Number(m[4] || 0);
        const absent = Number(m[5] || 0);
        const open = Number(m[6] || 0);
        const cases = m[7] ? `${m[7]}c` : "";
        const allOk = cur === tot && stale === 0 && blocked === 0 && absent === 0 && open === 0;
        const icon = allOk ? theme.fg("success", "●") : stale > 0 || open > 0 ? theme.fg("warning", "◐") : theme.fg("error", "○");
        const counts = allOk
          ? theme.fg("success", `${cur}/${tot}`)
          : theme.fg("warning", `${cur}/${tot}`);
        const extras: string[] = [];
        if (stale > 0) extras.push(theme.fg("warning", `${stale} stale`));
        if (blocked > 0) extras.push(theme.fg("error", `${blocked} blocked`));
        if (open > 0) extras.push(theme.fg("warning", `${open} open`));
        if (cases) extras.push(theme.fg("dim", cases));
        cachedStatusBadge = `${icon} ${theme.fg("muted", "drift")} ${counts}${extras.length ? ` ${extras.join(" ")}` : ""}`;
        return cachedStatusBadge;
      }
    } catch {
      // Ignore errors
    }
    cachedStatusBadge = "";
    return "";
  }

  function installCustomFooter(ctx: any) {
    if (footerInstalled || !ctx || ctx.mode !== "tui" || typeof ctx.ui?.setFooter !== "function") {
      return;
    }
    footerInstalled = true;
    ctx.ui.setFooter((tui: any, theme: any, footerData: any) => {
      const unsub = footerData.onBranchChange(() => tui.requestRender());
      return {
        dispose() {
          footerInstalled = false;
          unsub();
        },
        invalidate() {
          if (typeof ctx.isIdle !== "function" || ctx.isIdle()) {
            cachedStatusAt = 0;
          }
        },
        render(width: number): string[] {
          const sm = ctx.sessionManager;
          const sessionId = sm.getSessionId?.() ?? "";
          const leafId = sm.getLeafId?.() ?? null;
          const entries = sm.getEntries?.() ?? [];
          const entryCount = entries.length;
          if (
            !cachedUsage ||
            cachedSessionId !== sessionId ||
            cachedLeafId !== leafId ||
            cachedEntryCount !== entryCount
          ) {
            let input = 0;
            let output = 0;
            let cacheRead = 0;
            let cacheWrite = 0;
            let cost = 0;
            let latestCacheHitRate: number | undefined;
            for (const entry of entries) {
              const u =
                entry.type === "usage"
                  ? entry.usage
                  : entry.type === "message" &&
                      (entry.message?.role === "assistant" || entry.message?.role === "toolResult")
                    ? entry.message.usage
                    : (entry.type === "branch_summary" || entry.type === "compaction")
                      ? entry.usage
                      : undefined;
              if (u) {
                input += u.input || 0;
                output += u.output || 0;
                cacheRead += u.cacheRead || 0;
                cacheWrite += u.cacheWrite || 0;
                cost += u.cost?.total || 0;
                if (entry.type === "message" && entry.message?.role === "assistant") {
                  const promptTokens = (u.input || 0) + (u.cacheRead || 0) + (u.cacheWrite || 0);
                  latestCacheHitRate = promptTokens > 0 ? ((u.cacheRead || 0) / promptTokens) * 100 : undefined;
                }
              }
            }
            cachedSessionId = sessionId;
            cachedLeafId = leafId;
            cachedEntryCount = entryCount;
            cachedUsage = { input, output, cacheRead, cacheWrite, cost, latestCacheHitRate };
          }

          const cwd = sm.getCwd?.() || ctx.cwd || process.cwd();
          const pwd = formatCwd(cwd);
          const branch = footerData.getGitBranch?.();
          const sessionName = sm.getSessionName?.();
          const sepDot = theme.fg("dim", " · ");

          // Top line: path · branch · sessionName (left) | drift status badge (right)
          let topLeft = theme.fg("muted", pwd);
          if (branch) {
            topLeft += `${sepDot}${theme.fg("accent", `⎇ ${branch}`)}`;
          }
          if (sessionName) {
            topLeft += `${sepDot}${theme.fg("text", sessionName)}`;
          }
          const driftBadge = getDriftStatusBadge(cwd, theme);
          let topLine: string;
          if (driftBadge) {
            const leftW = visibleWidth(topLeft);
            const rightW = visibleWidth(driftBadge);
            if (leftW + 2 + rightW <= width) {
              topLine = topLeft + " ".repeat(width - leftW - rightW) + driftBadge;
            } else {
              topLine = truncateToWidth(topLeft, width, theme.fg("dim", "…"));
            }
          } else {
            topLine = truncateToWidth(topLeft, width, theme.fg("dim", "…"));
          }

          // Bottom line: tokens · €cost · context% (left) | model · thinking (right)
          const statsParts: string[] = [];
          if (cachedUsage.input > 0 || cachedUsage.output > 0) {
            statsParts.push(
              `${theme.fg("dim", "↑")}${theme.fg("muted", formatTokens(cachedUsage.input))} ${theme.fg("dim", "↓")}${theme.fg("muted", formatTokens(cachedUsage.output))}`,
            );
          }
          if (cachedUsage.cacheRead > 0 || cachedUsage.cacheWrite > 0) {
            const cacheParts: string[] = [];
            if (cachedUsage.cacheRead > 0) cacheParts.push(`R${formatTokens(cachedUsage.cacheRead)}`);
            if (cachedUsage.cacheWrite > 0) cacheParts.push(`W${formatTokens(cachedUsage.cacheWrite)}`);
            if (cachedUsage.latestCacheHitRate !== undefined) {
              cacheParts.push(`${cachedUsage.latestCacheHitRate.toFixed(0)}%`);
            }
            statsParts.push(theme.fg("dim", cacheParts.join(" ")));
          }
          if (cachedUsage.cost > 0) {
            statsParts.push(theme.fg("accent", `€${cachedUsage.cost.toFixed(3)}`));
          }

          const contextUsage = ctx.getContextUsage?.();
          const contextWindow = contextUsage?.contextWindow ?? ctx.model?.contextWindow ?? 0;
          const pctVal = contextUsage?.percent ?? 0;
          const pctStr = contextUsage?.percent !== null && contextUsage?.percent !== undefined ? `${pctVal.toFixed(1)}%` : "?";
          const ctxDisplay = contextWindow > 0 ? `${pctStr}/${formatTokens(contextWindow)}` : pctStr;
          const ctxColor = pctVal > 90 ? "error" : pctVal > 70 ? "warning" : "muted";
          statsParts.push(theme.fg(ctxColor, `ctx ${ctxDisplay}`));

          let statsLeft = statsParts.join(sepDot);
          let statsLeftW = visibleWidth(statsLeft);
          if (statsLeftW > width) {
            statsLeft = truncateToWidth(statsLeft, width, theme.fg("dim", "…"));
            statsLeftW = visibleWidth(statsLeft);
          }

          const modelId = ctx.model?.id || "no-model";
          let rightSide = theme.fg("muted", modelId);
          if (ctx.model?.reasoning) {
            const think = ctx.thinkingLevel || "off";
            const thinkStyle =
              think === "off"
                ? theme.fg("dim", "off")
                : theme.getThinkingBorderColor
                  ? theme.getThinkingBorderColor(think)(think)
                  : theme.fg("accent", think);
            rightSide += `${sepDot}${thinkStyle}`;
          }
          if (footerData.getAvailableProviderCount?.() > 1 && ctx.model?.provider) {
            const withProv = `${theme.fg("dim", `(${ctx.model.provider})`)} ${rightSide}`;
            if (statsLeftW + 2 + visibleWidth(withProv) <= width) {
              rightSide = withProv;
            }
          }

          const rightW = visibleWidth(rightSide);
          let statsLine: string;
          if (statsLeftW + 2 + rightW <= width) {
            statsLine = statsLeft + " ".repeat(width - statsLeftW - rightW) + rightSide;
          } else {
            const avail = width - statsLeftW - 2;
            if (avail > 0) {
              const truncRight = truncateToWidth(rightSide, avail, "");
              const pad = " ".repeat(Math.max(0, width - statsLeftW - visibleWidth(truncRight)));
              statsLine = statsLeft + pad + truncRight;
            } else {
              statsLine = statsLeft;
            }
          }

          const lines = [topLine, statsLine];
          const extStatuses = footerData.getExtensionStatuses?.();
          if (extStatuses && extStatuses.size > 0) {
            const sorted = Array.from(extStatuses.entries() as Iterable<[string, string]>)
              .sort(([a], [b]) => a.localeCompare(b))
              .map(([, t]) => t.replace(/[\r\n\t]+/gu, " ").replace(/ +/gu, " ").trim());
            lines.push(truncateToWidth(sorted.join(" "), width, theme.fg("dim", "…")));
          }
          return lines;
        },
      };
    });
  }

  pi.on("session_start", (_event: any, ctx: any) => {
    recovery.sessionStart();
    footerInstalled = false;
    lastUnownedKey = "";
    installCustomFooter(ctx);
  });

  function wrapCodeSpan(line: string): string {
    const content = line || "\u00a0";
    let longest = 0;
    for (const m of content.matchAll(/`+/gu)) {
      if (m[0].length > longest) longest = m[0].length;
    }
    const fence = "`".repeat(longest + 1);
    const pad = content.startsWith("`") || content.endsWith("`") ? " " : "";
    return `${fence}${pad}${content}${pad}${fence}`;
  }

  function styleTextLine(line: string): string {
    const kv = /^(\s*)(contract|check|gate|cases|open|adopted|impacts)(:\s*)(.*)$/u.exec(line);
    if (kv) {
      const [, ws, key, sep, rest] = kv;
      const styledRest = rest
        .replace(/\b(not green|stale|blocked|invalid|absent|red|missing)\b/gu, "\x1b[31m$1\x1b[39m")
        .replace(/\b(green|current|verified|bound|killed|none|0 finding\(s\))\b/gu, "\x1b[32m$1\x1b[39m")
        .replace(/·/gu, "\x1b[2m·\x1b[22m");
      return `${ws}\x1b[1m${key}\x1b[22m\x1b[2m${sep}\x1b[22m\x1b[39m${styledRest}`;
    }
    const rc = /^(\s*)(@recall|!must|>hook|~gotcha|\+nice|\?open)(\s+)(.*)$/u.exec(line);
    if (rc) {
      const [, ws, tag, sep, rest] = rc;
      const ansi =
        tag === "@recall"
          ? "\x1b[1;36m"
          : tag === "!must"
            ? "\x1b[1;33m"
            : tag === ">hook"
              ? "\x1b[1;34m"
              : tag === "~gotcha"
                ? "\x1b[1;31m"
                : tag === "+nice"
                  ? "\x1b[1;32m"
                  : "\x1b[1;35m";
      const styledRest = rest
        .replace(/\b(HIT)\b/gu, "\x1b[32m$1\x1b[39m")
        .replace(/\b(STALE)\b/gu, "\x1b[33m$1\x1b[39m")
        .replace(/\b(MISS)\b/gu, "\x1b[31m$1\x1b[39m");
      return `${ws}${ansi}${tag}\x1b[22;39m${sep}\x1b[39m${styledRest}`;
    }
    return line;
  }

  if (typeof pi.registerMarkdownTransformer === "function") {
    pi.registerMarkdownTransformer((markdown: string, context: any) => {
      if (context?.messageType === "assistant-thinking") {
        return markdown;
      }
      return markdown.replace(
        /(^|\n)([ \t]*)(`{3,}|~{3,})[ \t]*text[ \t]*\r?\n([\s\S]*?)\r?\n\2\3[ \t]*(?=\r?\n|$)/gu,
        (_m, lead: string, indent: string, _fence: string, body: string) => {
          const lines = body
            .split(/\r?\n/u)
            .map((line: string) => `${indent}  ${wrapCodeSpan(styleTextLine(line))}`);
          return `${lead}${lines.join("  \n")}`;
        },
      );
    });
  }

  pi.on("before_agent_start", async (event: any, ctx: any) => {
    installCustomFooter(ctx);
    recovery.beforeStart(event, ctx);
    if (!event || event.messageType !== "user") {
      return;
    }
    settledForCurrentPrompt = false;
    const area = getArea(ctx?.cwd || process.cwd());
    if (!area) {
      if (event.systemPromptOptions?.sections) {
        delete event.systemPromptOptions.sections.drift_context;
      }
      return;
    }
    const bin = getBin();
    let statsSummary = "";
    const contractsDir = join(area, ".drift", "contracts");
    if (bin && existsSync(contractsDir)) {
      try {
        const out = execFileSync(bin, ["status", contractsDir], {
          cwd: area,
          encoding: "utf-8",
          timeout: 2000,
          stdio: ["ignore", "pipe", "ignore"],
        });
        statsSummary = " " + out.trim().replace(/\s+/g, " ");
      } catch (e: any) {
        if (typeof e?.stdout === "string" && e.stdout.trim()) {
          statsSummary = " " + e.stdout.trim().replace(/\s+/g, " ");
        }
      }
    }
    const home = process.env.HOME || process.env.USERPROFILE || homedir();
    let driftSkill = "drift";
    if (home) {
      if (existsSync(join(home, ".agents", "skills", "drift-enterprise")) ||
          existsSync(join(home, ".copilot", "skills", "drift-enterprise"))) {
        driftSkill = "drift-enterprise";
      } else if (existsSync(join(home, ".agents", "skills", "drift-pro")) ||
          existsSync(join(home, ".copilot", "skills", "drift-pro"))) {
        driftSkill = "drift-pro";
      }
    }
    const contextText =
      process.env.DRIFT_EDITION === "free"
        ? `[DRIFT area active at ${area}.${statsSummary} ` +
          `For read-only Q&A or explanations that do not edit code or contracts, answer directly without loading DRIFT skills. ` +
          `When changing code or contracts in DRIFT Free, use drift check, drift fmt, drift review --brief, drift approve --by <owner>, drift prove, and drift gate.]`
        : `[DRIFT area active at ${area}.${statsSummary} ` +
          `For read-only Q&A or explanations that do not edit code or contracts, answer directly without loading DRIFT skills or writing recall cards. ` +
          `When changing code or contracts, follow the ${driftSkill} skill: (0) Orient first with drift recall query '<expr>' (e.g. 'feature @') before exploratory grep/view; on a MISS during contract/code work, record the discovered capsule in .drift-work/recall.jsonl. ` +
          `(1) Behaviour unchanged on covered code: 0 stops, use drift select --changed and drift gate --base. On uncovered code (0 matching contracts), a DRIFT split/refactor is a Baseline Carve-out: scaffold the contract(s) (drift new --from-recall --code), bind proof tests, and run drift review --brief instead of ending with no contract. ` +
          `(2) Multi-slice Wave: use 1 cohesive contract for uniform dispatch/handler splits, or N contracts when slices have distinct rules (<path>#<symbol> on shared files, decide_by = "execution" for non-blocking details), ` +
          `run 1 batch drift review .drift/contracts --brief --base, wait ONCE for owner drift approve .drift/contracts --by <owner>, ` +
          `then execute via drift plan --pack ready. Never piggyback new behaviour onto existing approved cases.]`;

    const entries = ctx?.sessionManager?.getEntries?.() ?? [];
    for (let i = entries.length - 1; i >= 0; i--) {
      const e = entries[i];
      if (e?.type === "custom_message" && e?.customType === "drift-context") {
        if (e.content === contextText) {
          return;
        }
        break;
      }
    }
    return {
      message: {
        role: "custom",
        customType: "drift-context",
        display: false,
        content: contextText,
      },
    };
  });

  pi.on("session_before_compact", (event: RecoveryEvent) => recovery.beforeCompact(event));
  pi.on("session_compact", (event: RecoveryEvent) => recovery.compacted(event));
  pi.on("session_compact_failed", () => recovery.failed());
  pi.on("agent_settled", () => recovery.settled());
  pi.on("agent_before_settle", (event: RecoveryEvent, ctx: RecoveryContext) =>
    recovery.beforeSettle(event, ctx));

  function emitGateMessage(content: string, event: any) {
    const entry = {
      type: "custom_message" as const,
      customType: "drift-gate-check",
      content,
      display: false,
    };
    if (Array.isArray(event?.entries)) {
      return {
        entries: [...event.entries, entry],
        continue: true,
      };
    }
    if (typeof pi.sendMessage === "function") {
      pi.sendMessage({ customType: "drift-gate-check", content, display: false }, { triggerTurn: true });
      return { entries: [entry], continue: true };
    }
    if (typeof pi.appendEntry === "function") {
      pi.appendEntry(entry);
    }
    return { entries: [entry], continue: true };
  }

  pi.on("agent_before_settle", async (event: any, ctx: any) => {
    if (settledForCurrentPrompt || event?.outcome === "error" || event?.outcome === "aborted") {
      return;
    }
    const area = getArea(ctx?.cwd || process.cwd());
    if (!area) {
      return;
    }
    const bin = getBin();
    if (!bin) {
      return;
    }
    try {
      execFileSync(bin, ["check", join(area, ".drift"), "--json"], {
        cwd: area,
        encoding: "utf-8",
        timeout: 3000,
        stdio: ["ignore", "pipe", "pipe"],
      });
    } catch (err) {
      settledForCurrentPrompt = true;
      const errMsg = describeCheckFailure(err, join(area, ".drift"));
      return emitGateMessage(errMsg, event);
    }
    if (process.env.DRIFT_EDITION === "free") {
      return;
    }
    try {
      const st = execFileSync("git", ["-C", area, "-c", "core.quotepath=false", "status", "--porcelain", "--untracked-files=normal"], {
        encoding: "utf-8",
        timeout: 2000,
        stdio: ["ignore", "pipe", "ignore"],
      });
      const changed = st
        .split(/\r?\n/u)
        .filter((l) => l.length >= 4 && l[0] !== "D" && l[1] !== "D")
        .map((l) => {
          let p = l.slice(3).trim();
          if ((l[0] === "R" || l[0] === "C" || l[1] === "R" || l[1] === "C") && p.includes(" -> ")) {
            p = p.split(" -> ").pop()!.trim();
          }
          return p.replace(/^"|"$/gu, "");
        })
        .filter((f) => f && !f.startsWith(".drift/") && /\.(v|java|kt|js|mjs|ts|tsx|py|go|rs)$/u.test(f) && existsSync(join(area, f)))
        .slice(0, 25);
      if (changed.length > 0) {
        const contractsDir = join(area, ".drift", "contracts");
        let impOut = "";
        let impOk = true;
        if (existsSync(contractsDir)) {
          try {
            const impArgs = ["impact", contractsDir, ...changed.flatMap((f) => ["--code", f]), "--json"];
            impOut = execFileSync(bin, impArgs, {
              cwd: area,
              encoding: "utf-8",
              timeout: 3000,
              stdio: ["ignore", "pipe", "ignore"],
            }).replace(/\s+/gu, "");
          } catch {
            impOk = false;
          }
        } else {
          impOut = '{"contracts":[],"unmatched_code":["uncontracted"]}';
        }
        if (impOk) {
          if (!impOut) {
            impOut = '{"contracts":[],"unmatched_code":["uncontracted"]}';
          }
          const dirtyC = execFileSync("git", ["-C", area, "status", "--porcelain", "--untracked-files=normal", "--", ".drift/contracts"], {
            encoding: "utf-8",
            timeout: 2000,
            stdio: ["ignore", "pipe", "ignore"],
          }).trim();
          if (impOut.includes('"unmatched_code":["') && (dirtyC || impOut.includes('"contracts":[]'))) {
            const unownedKey = `${area}:${changed.join("\n")}`;
            if (lastUnownedKey !== unownedKey) {
              lastUnownedKey = unownedKey;
              settledForCurrentPrompt = true;
              const unownedMsg = `Changed source files in ${area} are not covered by any contract scope.code (unmatched_code); whether this task owns them is unknown (working-tree evidence, not task attribution). Next: if this task changed them, scaffold the baseline contract(s) (drift new --from-recall --code) or run drift sweep --root ${area} --sync-scope; otherwise report them and leave them unchanged.`;
              return emitGateMessage(unownedMsg, event);
            }
          } else {
            lastUnownedKey = "";
          }
        }
      } else {
        lastUnownedKey = "";
      }
    } catch {
      // Ignore git/impact errors outside Git worktrees.
    }
  });
}
