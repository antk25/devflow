import { readFileSync, realpathSync } from "node:fs";
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

export default function devflow(pi: ExtensionAPI) {
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

	pi.on("session_start", (_event, ctx) => {
		try {
			instructions();
			if (ctx.model?.provider === "claude-bridge") stop(ctx, reason);
		} catch (error) {
			stop(ctx, `DevFlow: общие инструкции недоступны: ${error}; запустите ./install.sh`);
		}
	});

	pi.on("before_agent_start", (event, ctx) => {
		if (ctx.model?.provider === "claude-bridge") {
			stop(ctx, reason);
			return;
		}
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
