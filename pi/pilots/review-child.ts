import { lstatSync, realpathSync, readdirSync, statSync } from "node:fs";
import { isAbsolute, relative, resolve, sep } from "node:path";
import type { ExtensionAPI, ToolCallEvent, ToolCallEventResult } from "@earendil-works/pi-coding-agent";
import { registerDevflow } from "../extensions/devflow.ts";

const deny = (): ToolCallEventResult => ({ block: true, reason: "DevFlow review: вызов вне строгого режима чтения; разрешение через UI невозможно." });
const closed = /(^|\/)(?:\.git|\.devflow|\.pi|\.claude|\.ssh|secrets?|credentials?|review-conformance)(?:\/|$)|(^|\/)\.env(?:\.|$)|review-conformance|bench\/combos\/all-fable\.json|\.(?:db|sqlite|pem|key)(?:[.-]|$)/i;
export const REVIEW_GIT = "git --no-pager --no-optional-locks -c core.fsmonitor=false -c core.hooksPath=/dev/null -c core.untrackedCache=false";

function safePath(input: unknown, cwd: string, directory = false): boolean {
	if (typeof input !== "string" || !input || input.includes("\0")) return false;
	const root = realpathSync(cwd);
	const path = resolve(root, input);
	const rel = relative(root, path).split(sep).join("/");
	if (rel === ".." || rel.startsWith("../") || isAbsolute(rel) || closed.test(rel)) return false;
	// No symlinks, including links whose destination happens to remain in the workspace.
	let cursor = root;
	for (const part of rel.split("/").filter(Boolean)) {
		cursor = resolve(cursor, part);
		if (lstatSync(cursor).isSymbolicLink()) return false;
	}
	if (!directory) return statSync(path).isFile();
	if (!statSync(path).isDirectory()) return false;
	// Search tools recurse internally: reject a scope containing any closed entry.
	const pending = [path];
	let count = 0;
	while (pending.length) {
		for (const entry of readdirSync(pending.pop()!, { withFileTypes: true })) {
			if (++count > 10000) return false;
			const child = resolve(entry.parentPath, entry.name);
			if (entry.isSymbolicLink() || closed.test(relative(root, child).split(sep).join("/"))) return false;
			if (entry.isDirectory()) pending.push(child);
			else if (!entry.isFile()) return false;
		}
	}
	return true;
}

const targetKey = Symbol.for("devflow.review-target.v1");
const targets: Map<string, readonly string[]> = ((globalThis as any)[targetKey] ??= new Map());

export function bindReviewTarget(cwd: string, revisions: readonly string[]) {
	const root = realpathSync(cwd);
	if (!revisions.length || revisions.some(value => !/^[a-f0-9]{40}(?:\.\.[a-f0-9]{40})?$/.test(value))) {
		throw new Error("Нужны разрешённые SHA target");
	}
	if (targets.has(root)) throw new Error("Target для cwd уже зарегистрирован");
	const snapshot = Object.freeze([...revisions]);
	targets.set(root, snapshot);
	return { dispose() { if (targets.get(root) === snapshot) targets.delete(root); } };
}

function safeBash(command: unknown, cwd: string, revisions: readonly string[]): boolean {
	if (typeof command !== "string") return false;
	if (command === "devflow context") return true;
	if (Object.keys(process.env).some(key => key.startsWith("GIT_"))) return false;
	if (!command.startsWith(REVIEW_GIT + " ")) return false;
	const tail = command.slice(REVIEW_GIT.length + 1);
	if (["status --porcelain=v1 --untracked-files=all --ignore-submodules=all", "rev-parse --verify HEAD", "ls-files"].includes(tail)) return true;
	const match = /^(show|diff) --no-ext-diff --no-textconv (HEAD|[a-f0-9]{40}(?:\.\.[a-f0-9]{40})?) -- ([A-Za-z0-9_./-]+)$/.exec(tail);
	return !!match && revisions.includes(match[2]) && !match[3].startsWith("-") && !match[3].split("/").includes("..") && safePath(match[3], cwd);
}

export function checkReviewTool(event: ToolCallEvent, cwd: string, revisions: readonly string[] = []): ToolCallEventResult | undefined {
	try {
		const input = event.input as Record<string, unknown>;
		if (event.toolName === "bash") return safeBash(input.command, cwd, revisions) ? undefined : deny();
		if (event.toolName === "read") return safePath(input.path, cwd) ? undefined : deny();
		if (event.toolName === "grep") {
			const path = input.path ?? ".";
			return safePath(path, cwd) || safePath(path, cwd, true) ? undefined : deny();
		}
		if (["ls", "find"].includes(event.toolName)) return safePath(input.path ?? ".", cwd, true) ? undefined : deny();
		return deny();
	} catch { return deny(); }
}

export function registerReviewChild(pi: ExtensionAPI): void {
	let binding: { root: string; revisions: readonly string[] | undefined } | undefined;
	pi.on("tool_call", (event, ctx) => {
		try {
			const root = realpathSync(ctx.cwd);
			binding ??= { root, revisions: targets.get(root) };
			if (binding.root !== root || targets.get(root) !== binding.revisions) return deny();
			return checkReviewTool(event, root, binding.revisions);
		} catch { return deny(); }
	});
	registerDevflow(pi, { restoreContext: false });
	pi.on("before_agent_start", event => {
		event.systemPromptOptions.sections.devflow_review_readonly =
			`Только чтение. Bash допускает devflow context и фиксированный префикс ${REVIEW_GIT}, затем ` +
			"status --porcelain=v1 --untracked-files=all --ignore-submodules=all; rev-parse --verify HEAD; ls-files; " +
			"show|diff --no-ext-diff --no-textconv <согласованный полный SHA/диапазон SHA> -- <один безопасный файл>. " +
			"Закрытые файлы и ссылки исключены. Иные формы не разрешены; не обходи отказ.";
	});
}

export default registerReviewChild;
