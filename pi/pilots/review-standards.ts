import { mkdirSync, mkdtempSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { createRequire } from "node:module";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { parseFrontmatter } from "@earendil-works/pi-coding-agent";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export const REVIEW_AGENT = "devflow.review-standards";
export const REVIEW_MODEL = "openai-codex/gpt-6.1-sol";
const here = dirname(realpathSync(fileURLToPath(import.meta.url)));

export function reviewRole() {
	const source = readFileSync(resolve(here, "../../agents/review-standards.md"), "utf8");
	const { frontmatter, body } = parseFrontmatter(source);
	const map: Record<string, string[]> = { Read: ["read"], Grep: ["grep"], Glob: ["find", "ls"], Bash: ["bash"] };
	const tools = [...new Set(String(frontmatter.tools).split(",").flatMap(name => {
		const mapped = map[name.trim()];
		if (!mapped) throw new Error("Неизвестный инструмент роли review-standards");
		return mapped;
	}))];
	return { description: String(frontmatter.description), systemPrompt: body.trim() + "\n", tools,
		model: REVIEW_MODEL, thinking: "low", extensions: [], inheritProjectContext: true,
		inheritGlobalContext: false, inheritSkills: false, allowNestedSubagents: false,
		acceptanceRole: "read-only", timeoutMs: 600000 };
}

export async function pilotApi(packagePath: string, subpath: string) {
	if (!isAbsolute(packagePath)) throw new Error("Нужен абсолютный путь проверенного пакета");
	const root = realpathSync(packagePath);
	const manifest = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
	if (manifest.name !== "pi-subagents" || manifest.version !== "0.80.0" ||
		manifest.repository?.url !== "git+https://github.com/nicobailon/pi-subagents.git") {
		throw new Error("Пакет не совпадает с утверждённым pi-subagents@0.80.0");
	}
	const require = createRequire(join(root, "package.json"));
	return import(pathToFileURL(require.resolve(`pi-subagents/${subpath}`)).href);
}

export async function registerReviewSession(pi: ExtensionAPI, sessionId: string, packagePath: string) {
	const { registerRequiredChildExtensions } = await pilotApi(packagePath, "required-child-extensions");
	const required = registerRequiredChildExtensions({ sessionId,
		extensions: [{ id: "devflow.review-child", path: join(here, "review-child.ts") }], requireForAllRunners: true });
	try {
		const request: any = { version: 1, name: REVIEW_AGENT, definition: reviewRole() };
		pi.events.emit("pi-subagents:runtime-agent-register:v1", request);
		if (!request.result) throw new Error("pi-subagents: регистрация runtime-агента недоступна");
		if (!request.result.ok) throw request.result.error;
		let disposed = false;
		return { dispose() {
			if (disposed) return;
			disposed = true;
			try { request.result.registration.dispose(); } finally { required.dispose(); }
		} };
	} catch (error) { required.dispose(); throw error; }
}

export type ReviewOutcome = { outcome: string; reason?: string };
export type ReviewIdentity = { requestId: string; ownerRunId: string; nodeId: string };
type Terminal = { status: string; model?: string; thinking?: string; exitCode?: number; text?: string };
export type ReviewState = ReviewOutcome & {
	identity: ReviewIdentity;
	taskStatus: string;
	terminal?: Terminal;
	disposeResolved?: boolean;
	shutdownConfirmed?: boolean;
	noActiveWorkConfirmed?: boolean;
	deadline?: number;
	final: boolean;
	originalReason?: string;
};
export type ReviewSignal = ReviewIdentity & (
	{ kind: "terminal"; terminal: Terminal } |
	{ kind: "cancel" } | { kind: "tick" } |
	{ kind: "cleanup"; disposeResolved?: boolean; shutdownConfirmed?: boolean; noActiveWorkConfirmed?: boolean }
);

export function settleReview(taskStatus: string, shutdownConfirmed: boolean | undefined,
	noActiveWorkConfirmed: boolean | undefined): ReviewOutcome {
	if (shutdownConfirmed !== true || noActiveWorkConfirmed !== true) {
		return { outcome: "unavailable", reason: "lifecycle_unverifiable" };
	}
	if (["completed", "cancelled", "interrupted", "timed_out", "failed", "empty_response"].includes(taskStatus)) {
		return { outcome: taskStatus };
	}
	return { outcome: "failed", reason: "invalid_terminal" };
}

// Чистый редуктор: synthetic cleanup проверяет логику, но не добавляет ack в API пакета.
export function reduceReview(state: ReviewState, signal: ReviewSignal, now: number): ReviewState {
	if (state.final || ["requestId", "ownerRunId", "nodeId"].some(key =>
		state.identity[key as keyof ReviewIdentity] !== signal[key as keyof ReviewIdentity])) return state;
	let next = { ...state };
	if (next.deadline !== undefined && now >= next.deadline) {
		return { ...next, outcome: "unavailable", reason: "cleanup_unconfirmed", final: true };
	}
	if (signal.kind === "terminal" && !next.terminal) {
		next.terminal = { ...signal.terminal };
		next.taskStatus = signal.terminal.status;
		next.originalReason ??= signal.terminal.status;
		next.deadline ??= now + 10000;
	} else if (signal.kind === "cancel") {
		next.taskStatus = "cancelled";
		next.originalReason ??= "cancelled";
		next.deadline ??= now + 10000;
	} else if (signal.kind === "cleanup") {
		for (const key of ["disposeResolved", "shutdownConfirmed", "noActiveWorkConfirmed"] as const) {
			// Первое свидетельство окончательно; повторы не могут превратить ошибку в успех.
			if (next[key] === undefined && signal[key] !== undefined) next[key] = signal[key];
		}
	}
	if (next.deadline === undefined) return next;
	let status = next.taskStatus;
	if (status === "completed") {
		const terminal = next.terminal!;
		if (terminal.model !== REVIEW_MODEL || terminal.thinking !== "low" || terminal.exitCode !== 0) status = "failed";
		else if (!terminal.text?.trim()) status = "empty_response";
	}
	const settled = settleReview(status, next.shutdownConfirmed, next.noActiveWorkConfirmed);
	return { ...next, ...settled, final: settled.outcome !== "unavailable" };
}

export function unavailableReview(): ReviewState {
	return { identity: { requestId: "not_started", ownerRunId: "not_started", nodeId: "not_started" },
		taskStatus: "not_started", outcome: "unavailable", reason: "lifecycle_unverifiable", final: true };
}

export function saveReviewEvidence(state: ReviewState): string {
	const root = join(homedir(), ".local/state/devflow/pi-subagents-pilot");
	mkdirSync(root, { recursive: true, mode: 0o700 });
	const directory = mkdtempSync(join(root, "interactive-"));
	// Только закрытый набор диагностических полей: ни target, ни текст/ошибки, ни окружение.
	const statuses = ["not_started", "completed", "cancelled", "interrupted", "timed_out", "failed", "empty_response", "unavailable"];
	const safeStatus = (value: string | undefined) => statuses.includes(value ?? "") ? value : "unknown";
	const confirmation = (value: boolean | undefined) => value === undefined ? "unknown" : value;
	const manifest = { packageVersion: "0.80.0", realModelSession: false,
		terminalStatus: safeStatus(state.terminal?.status), taskStatus: safeStatus(state.taskStatus),
		disposeResolved: confirmation(state.disposeResolved), shutdownConfirmed: confirmation(state.shutdownConfirmed),
		noActiveWorkConfirmed: confirmation(state.noActiveWorkConfirmed), outcome: safeStatus(state.outcome),
		reason: ["lifecycle_unverifiable", "cleanup_unconfirmed", "invalid_terminal"].includes(state.reason ?? "") ? state.reason : "unknown",
		originalReason: safeStatus(state.originalReason) };
	writeFileSync(join(directory, "manifest.json"), JSON.stringify(manifest, null, 2) + "\n", { mode: 0o600 });
	writeFileSync(join(directory, "report.md"), "# Пилот review-standards\n\nРеальное ревью и совместимость не доказаны.\n\n```json\n" +
		JSON.stringify(manifest, null, 2) + "\n```\n", { mode: 0o600 });
	return directory;
}

export default function reviewStandards(pi: ExtensionAPI) {
	if (process.env.DEVFLOW_SUBAGENTS_PILOT_PACKAGE) {
		pi.registerCommand("devflow-review-standards", {
			description: "Пилот недоступен: жизненный цикл pi-subagents@0.80.0 не доказан",
			handler: async (_target, ctx) => {
				const evidence = saveReviewEvidence(unavailableReview());
				ctx.ui.notify(`unavailable/lifecycle_unverifiable. Ревью не запускалось. ${evidence}`, "warning");
			},
		});
	}
	let registration: { dispose(): void } | undefined;
	pi.on("session_start", async (_event, ctx) => {
		registration?.dispose();
		registration = undefined;
		const path = process.env.DEVFLOW_SUBAGENTS_PILOT_PACKAGE;
		if (path) registration = await registerReviewSession(pi, ctx.sessionManager.getSessionId(), path);
	});
	pi.on("session_shutdown", () => {
		registration?.dispose();
		registration = undefined;
	});
}
