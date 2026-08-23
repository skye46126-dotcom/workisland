import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const require = createRequire(import.meta.url);
const dir = mkdtempSync(join(tmpdir(), "wi-tokens-"));

// stats-service 在模块加载时就调用 electron.app.getPath("userData")，而普通 node
// 下 require("electron") 只会返回二进制路径字符串。先往 require 缓存里塞一个桩，
// 才能在 Electron 之外直接测这些主进程模块。
const electronId = require.resolve("electron");
require.cache[electronId] = {
  id: electronId,
  filename: electronId,
  loaded: true,
  exports: { app: { getPath: () => dir }, ipcMain: { on() {}, handle() {}, removeListener() {}, removeHandler() {} } }
};

const { parseClaudeTokens, parseCodexTokens } = require("../src/main/adapters-extended.cjs");
const { isCodexDesktopAppCommand } = require("../src/main/process-monitor.cjs");
const { createSessionState } = require("../src/main/session-state.cjs");
const write = (name, lines) => {
  const file = join(dir, name);
  writeFileSync(file, lines.map((l) => (typeof l === "string" ? l : JSON.stringify(l))).join("\n"));
  return file;
};

// ── Claude transcript ────────────────────────────────────────────────────────
test("claude token parser sums assistant usage across the transcript", async () => {
  const file = write("claude.jsonl", [
    { type: "user", message: { content: "hi" } },
    { type: "assistant", requestId: "r1", message: { model: "claude-x", usage: { input_tokens: 10, output_tokens: 5, cache_read_input_tokens: 100, cache_creation_input_tokens: 20 } } },
    { type: "assistant", requestId: "r2", message: { model: "claude-x", usage: { input_tokens: 7, output_tokens: 3, cache_read_input_tokens: 50 } } },
    "",
    "{ not json",
    { type: "system", message: { usage: { input_tokens: 999, output_tokens: 999 } } }
  ]);
  const result = await parseClaudeTokens(file);
  assert.deepEqual(result, {
    inputTokens: 17,
    outputTokens: 8,
    cacheReadTokens: 150,
    cacheCreationTokens: 20,
    totalTokens: 25,
    model: "claude-x",
    isEstimated: false
  });
});

test("claude token parser de-duplicates repeated request ids", async () => {
  const usage = { input_tokens: 10, output_tokens: 5 };
  const file = write("claude-dupe.jsonl", [
    { type: "assistant", requestId: "r1", message: { usage } },
    { type: "assistant", requestId: "r1", message: { usage } },
    { type: "assistant", requestId: "r2", message: { usage } }
  ]);
  const result = await parseClaudeTokens(file);
  assert.equal(result.inputTokens, 20, "the repeated r1 record must not be counted twice");
  assert.equal(result.outputTokens, 10);
});

test("claude token parser returns null for an empty or unreadable transcript", async () => {
  assert.equal(await parseClaudeTokens(write("claude-empty.jsonl", [])), null);
  assert.equal(await parseClaudeTokens(join(dir, "does-not-exist.jsonl")), null);
});

// ── Codex rollout ────────────────────────────────────────────────────────────
test("codex token parser takes the last cumulative total and splits cached input out", async () => {
  const file = write("codex.jsonl", [
    { payload: { type: "thread_settings_applied", thread_settings: { model: "gpt-x" } } },
    { payload: { type: "token_count", info: { total_token_usage: { input_tokens: 100, cached_input_tokens: 40, output_tokens: 20 } } } },
    { payload: { type: "token_count", info: { total_token_usage: { input_tokens: 300, cached_input_tokens: 120, output_tokens: 60, cache_write_input_tokens: 9 } } } }
  ]);
  const result = await parseCodexTokens(file);
  assert.equal(result.inputTokens, 180, "cached tokens are reported separately, not inside input");
  assert.equal(result.cacheReadTokens, 120);
  assert.equal(result.cacheCreationTokens, 9);
  assert.equal(result.outputTokens, 60);
  assert.equal(result.totalTokens, 240);
  assert.equal(result.model, "gpt-x");
});

test("codex token parser returns null when the rollout carries no token_count", async () => {
  const file = write("codex-none.jsonl", [{ payload: { type: "thread_settings_applied", thread_settings: { model: "gpt-x" } } }]);
  assert.equal(await parseCodexTokens(file), null);
});

// ── Codex Desktop 进程识别 ───────────────────────────────────────────────────
test("codex desktop detection covers both the standalone app and the ChatGPT.app bundle", () => {
  assert.equal(isCodexDesktopAppCommand("/Applications/Codex.app/Contents/MacOS/Codex"), true);
  assert.equal(isCodexDesktopAppCommand("/Applications/Codex Desktop.app/Contents/MacOS/Codex"), true);
  assert.equal(
    isCodexDesktopAppCommand("/Applications/ChatGPT.app/Contents/Frameworks/Codex Framework.framework/Versions/A/codex"),
    true,
    "newer Codex Desktop builds ship inside ChatGPT.app"
  );
  assert.equal(isCodexDesktopAppCommand("/Applications/ChatGPT.app/Contents/MacOS/ChatGPT"), false, "plain ChatGPT is not a Codex session host");
  assert.equal(isCodexDesktopAppCommand("/Applications/Claude.app/Contents/MacOS/Claude"), false);
});

// ── 每轮计时 ─────────────────────────────────────────────────────────────────
function reduceAll(events) {
  const api = createSessionState({ isVisibleInIsland: () => true });
  let state = api.createInitialState();
  for (const event of events) state = api.apply(state, event);
  return state;
}

test("a new turn refreshes turnStartedAt but keeps createdAt for the whole conversation", () => {
  const state = reduceAll([
    { type: "sessionStarted", sessionId: "s1", tool: "claude", timestamp: 1000 },
    { type: "sessionCompleted", sessionId: "s1", tool: "claude", timestamp: 2000 },
    { type: "sessionStarted", sessionId: "s1", tool: "claude", timestamp: 5000 }
  ]);
  const session = state.sessions.get("s1");
  assert.equal(session.createdAt, 1000, "createdAt keeps whole-conversation semantics (stats depend on it)");
  assert.equal(session.turnStartedAt, 5000, "the card timer counts the current turn only");
});

test("turnStarted also advances only the per-turn clock", () => {
  const state = reduceAll([
    { type: "sessionStarted", sessionId: "s2", tool: "claude", timestamp: 1000 },
    { type: "turnStarted", sessionId: "s2", tool: "claude", timestamp: 4000 }
  ]);
  const session = state.sessions.get("s2");
  assert.equal(session.createdAt, 1000);
  assert.equal(session.turnStartedAt, 4000);
});

test("a session that genuinely ended restarts its whole-conversation clock", () => {
  const state = reduceAll([
    { type: "sessionStarted", sessionId: "s3", tool: "claude", timestamp: 1000 },
    { type: "sessionCompleted", sessionId: "s3", tool: "claude", timestamp: 2000, isSessionEnd: true },
    { type: "sessionStarted", sessionId: "s3", tool: "claude", timestamp: 9000 }
  ]);
  const session = state.sessions.get("s3");
  assert.equal(session.createdAt, 9000);
  assert.equal(session.turnStartedAt, 9000);
});

test("sessions recovered from a transcript stay flagged so the idle sweep spares them", () => {
  const state = reduceAll([
    { type: "sessionStarted", sessionId: "s4", tool: "claude", timestamp: 1000, recoveredFromTranscript: true, recoveryTranscriptPath: "/tmp/a.jsonl" }
  ]);
  const session = state.sessions.get("s4");
  assert.equal(session.recoveredFromTranscript, true);
  assert.equal(session.recoveryTranscriptPath, "/tmp/a.jsonl");
  const live = reduceAll([{ type: "sessionStarted", sessionId: "s5", tool: "claude", timestamp: 1000 }]);
  assert.equal(live.sessions.get("s5").recoveredFromTranscript, false, "hook-driven sessions must not be flagged");
});
