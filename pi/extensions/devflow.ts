import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const reason = "DevFlow: claude-bridge запрещён; выберите прямого провайдера, например anthropic/*.";

export default function devflow(pi: ExtensionAPI) {
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
