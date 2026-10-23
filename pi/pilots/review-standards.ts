import { readFileSync, realpathSync } from "node:fs";
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

export default function reviewStandards(pi: ExtensionAPI) {
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
