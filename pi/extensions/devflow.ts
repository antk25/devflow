import { existsSync, readFileSync, realpathSync } from "node:fs";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const reason = "DevFlow: claude-bridge запрещён; выберите прямого провайдера, например anthropic/*.";

export function checkTool(event: unknown, cwd: string, launch = spawn): Promise<any> {
	return new Promise((accept, reject) => {
		const root = resolve(dirname(realpathSync(fileURLToPath(import.meta.url))), "../..");
		const child = launch(join(root, "scripts/devflow-cli.sh"), ["guard", "--host", "pi"], {
			cwd, stdio: ["pipe", "pipe", "pipe"], timeout: 10000,
		});
		let output = "";
		child.stdout.on("data", chunk => {
			output += chunk;
			if (output.length > 1024 * 1024) child.kill();
		});
		child.stderr.resume();
		child.on("error", reject);
		child.stdin.on("error", reject);
		child.on("close", code => {
			try {
				if (code !== 0) throw new Error(`guard exit ${code}`);
				const result = JSON.parse(output);
				if (!["allow", "ask", "deny"].includes(result.decision) ||
					typeof result.reason !== "string" || typeof result.rule !== "string") {
					throw new Error("Неверный вердикт guard");
				}
				accept(result);
			} catch (error) { reject(error); }
		});
		child.stdin.end(JSON.stringify({ ...(event as object), cwd }));
	});
}

export async function guardTool(event: any, ctx: ExtensionContext, check = checkTool) {
	try {
		const result = await check(event, ctx.cwd);
		if (!["allow", "ask", "deny"].includes(result.decision) || typeof result.reason !== "string") {
			throw new Error("Неверный вердикт guard");
		}
		if (result.decision === "allow") return;
		if (result.decision === "ask" && ctx.hasUI &&
			await ctx.ui.confirm("DevFlow: разрешить этот вызов?", JSON.stringify(event.input) + "\n" + result.reason)) return;
		return { block: true, reason: `${result.reason} Вызов не выполнен; измените запрос или подтвердите его в UI.` };
	} catch (error) {
		return { block: true, reason: `DevFlow: проверка guard недоступна (${error}); вызов не выполнен. Исправьте guard перед повтором.` };
	}
}

function devflowRoot() {
	return resolve(dirname(realpathSync(fileURLToPath(import.meta.url))), "../..");
}

export function registerDevflow(pi: ExtensionAPI, options: { restoreContext?: boolean } = {}) {
	let level = "";
	let restored = "";
	function tell(ctx: ExtensionContext, text: string, kind: "info" | "warning" | "error" = "warning") {
		if (ctx.hasUI) ctx.ui.notify(text, kind);
		else console.error(text);
		pi.sendMessage({ customType: "devflow-context", content: text, display: true }, { triggerTurn: false });
	}
	function sessionId(ctx: ExtensionContext) {
		try { return ctx.sessionManager?.getSessionId?.() || ""; } catch { return ""; }
	}
	function knownTokens(ctx: ExtensionContext) {
		const usage = ctx.getContextUsage?.();
		const tokens = usage?.tokens;
		return typeof tokens === "number" && Number.isFinite(tokens) && tokens >= 0
			? { tokens, window: usage!.contextWindow } : undefined;
	}
	async function contextWarning(ctx: ExtensionContext) {
		const usage = knownTokens(ctx);
		let next = "unknown";
		let text = "CONTEXT_UNKNOWN: размер контекста неизвестен; это не нулевой контекст. Перед большой работой проверьте /session.";
		if (usage) {
			const args = ["context-level", "--tokens", String(usage.tokens)];
			if (usage.window > 0) args.push("--window", String(usage.window));
			const session = sessionId(ctx);
			if (session) args.push("--session", session);
			try {
				const result = await pi.exec(join(devflowRoot(), "scripts/devflow-cli.sh"), args, { cwd: ctx.cwd, timeout: 10000 });
				if (result.code !== 0) throw new Error(result.stderr || `exit ${result.code}`);
				({ level: next, text } = JSON.parse(result.stdout));
			} catch (error) {
				next = "error";
				text = `DevFlow: devflow context-level недоступен (${error}); порог контекста не проверен.`;
			}
		}
		if (next === level) return;
		level = next;
		if (next === "ok") return;
		tell(ctx, text, next === "error" ? "error" : "warning");
	}
	pi.on("turn_end", (_event, ctx) => contextWarning(ctx));
	pi.on("session_before_compact", async (event, ctx) => {
		if (options.restoreContext === false || !ctx.cwd || !existsSync(join(ctx.cwd, "AGENTS.md"))) return;
		const session = sessionId(ctx);
		if (!session) return;
		const args = ["handoff", "auto", "--session", session,
			"--trigger", event.reason === "manual" ? "manual" : "auto", "--host", "pi"];
		const usage = knownTokens(ctx);
		if (usage) args.push("--context-tokens", String(usage.tokens));
		try {
			const result = await pi.exec(join(devflowRoot(), "scripts/devflow-cli.sh"), ["--cwd", ctx.cwd, ...args],
				{ cwd: ctx.cwd, timeout: 10000 });
			if (result.code !== 0) throw new Error(result.stderr || `exit ${result.code}`);
			const handoff = result.stdout.trim() ? JSON.parse(result.stdout) : undefined;
			if (handoff?.instructions) tell(ctx, handoff.instructions, "info");
		} catch (error) {
			tell(ctx, `DevFlow: передача при сжатии не записана (${error}). Сжатие не отменяется.`, "error");
		}
	});
	pi.on("session_compact", async (_event, ctx) => {
		level = "";
		if (options.restoreContext === false || !pi.exec || !ctx.cwd) return;
		const result = await pi.exec("python3", [join(devflowRoot(), "scripts/launch.py"), "--restore-context"],
			{ cwd: ctx.cwd, timeout: 10000 });
		restored = result.code === 0 ? result.stdout :
			`Восстановление недоступно: ${result.stderr}. Не создавай новое состояние; сначала устрани ошибку.`;
		if (restored) tell(ctx, restored, result.code === 0 ? "info" : "error");
	});
	pi.on("tool_call", (event, ctx) => guardTool(event, ctx));
	function stop(ctx: ExtensionContext, message: string) {
		if (ctx.hasUI) ctx.ui.notify(message, "error");
		else console.error(message);
		ctx.abort();
		ctx.shutdown();
	}

	function instructions() {
		const path = process.env.DEVFLOW_INSTRUCTIONS ?? join(homedir(), ".claude", "devflow-instructions.md");
		const text = readFileSync(path, "utf8").trim();
		if (!text) throw new Error(`Пустые общие инструкции: ${path}`);
		return text;
	}

	pi.on("session_start", async (_event, ctx) => {
		level = "";
		restored = "";
		try {
			instructions();
			if (ctx.model?.provider === "claude-bridge") { stop(ctx, reason); return; }
			if (options.restoreContext !== false && pi.exec && ctx.cwd) {
				const result = await pi.exec("python3", [join(devflowRoot(), "scripts/launch.py"), "--restore-context"],
					{ cwd: ctx.cwd, timeout: 10000 });
				restored = result.code === 0 ? result.stdout :
					`Восстановление недоступно: ${result.stderr}. Не создавай новое состояние; сначала устрани ошибку.`;
				if (restored && ctx.hasUI) ctx.ui.notify(restored, result.code === 0 ? "info" : "error");
			}
		} catch (error) {
			stop(ctx, `DevFlow: общие инструкции недоступны: ${error}; запустите ./install.sh`);
		}
	});

	pi.on("before_agent_start", async (event, ctx) => {
		if (ctx.model?.provider === "claude-bridge") {
			stop(ctx, reason);
			return;
		}
		if (ctx.getContextUsage) await contextWarning(ctx);
		if (restored) event.systemPromptOptions.sections.devflow_restore =
			"Актуальное восстановление (заменяет снимок launcher):\n" + restored;
		try {
			event.systemPromptOptions.sections.devflow_shared = instructions();
			event.systemPromptOptions.sections.devflow_host =
				"Хост: pi. Не вызывать claude/claude-bridge. Прямой anthropic/* разрешён. " +
				"Фазы запускаются через devflow phase run, не Agent/SendMessage. " +
				"Implement выполняет ровно один шаг в свежем контексте и не публикует результат. " +
				"Для новой сессии пользователь использует /new, не /clear.";
		} catch (error) {
			stop(ctx, `DevFlow: общие инструкции недоступны: ${error}`);
		}
	});

	pi.on("model_select", async (event, ctx) => {
		if (event.model.provider !== "claude-bridge") return;
		ctx.abort();
		if (event.previousModel && event.previousModel.provider !== "claude-bridge" &&
			await pi.setModel(event.previousModel)) {
			if (ctx.hasUI) ctx.ui.notify(reason, "error");
			else console.error(reason);
			return;
		}
		stop(ctx, reason);
	});
}

export default function devflow(pi: ExtensionAPI) {
	registerDevflow(pi);
}
