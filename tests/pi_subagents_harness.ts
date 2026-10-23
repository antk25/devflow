import assert from "node:assert/strict";
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { EventEmitter } from "node:events";
import * as sdk from "@earendil-works/pi-coding-agent";
import { checkTool, guardTool } from "../pi/extensions/devflow.ts";
import { REVIEW_GIT, bindReviewTarget, checkReviewTool, registerReviewChild } from "../pi/pilots/review-child.ts";
import { pilotApi, registerReviewSession, reviewRole } from "../pi/pilots/review-standards.ts";

export default async function () {
	const fixture = process.env.DEVFLOW_TEST_FIXTURE!;
	if (process.env.DEVFLOW_TEST_TARGET_PROBE) {
		const handlers: any[] = [];
		registerReviewChild({ on(name: string, handler: any) {
			if (name === "tool_call") handlers.push(handler);
		} } as any);
		assert.equal(handlers.length, 2);
		const results = [];
		for (const hasUI of [false, true]) {
			for (const verb of ["show", "diff"]) {
				const unavailable = process.env.DEVFLOW_TEST_TARGET_PROBE === "unavailable";
				const event = unavailable
					? { type: "tool_call", toolCallId: "unavailable", toolName: "read", input: { path: "safe.txt" } }
					: { type: "tool_call", toolCallId: "foreign-target", toolName: "bash",
						input: { command: `${REVIEW_GIT} ${verb} --no-ext-diff --no-textconv ${"a".repeat(40)} -- safe.txt` } };
				const verdicts = [];
				for (const handler of handlers) verdicts.push(await handler(event,
					{ cwd: fixture, hasUI, ui: { confirm: async () => true } }));
				if (unavailable) {
					assert.equal(verdicts[0], undefined);
					assert.equal(verdicts[1]?.block, true);
					assert.ok(verdicts[1].reason.includes("недоступна"));
				}
				results.push({ verb, hasUI, blocked: verdicts.some(result => result?.block) });
			}
		}
		writeFileSync(join(process.env.DEVFLOW_TEST_EVIDENCE!, "target-probe.json"), JSON.stringify(results));
		assert.ok(results.every(result => result.blocked), JSON.stringify(results));
		return;
	}
	const packagePath = process.env.DEVFLOW_SUBAGENTS_PILOT_PACKAGE!;
	const external = process.env.DEVFLOW_TEST_EVIDENCE!;
	const load = (path: string) => import(pathToFileURL(join(packagePath, path)).href);
	const { buildInProcessChildLaunch } = await load("src/runs/shared/child-launch.js");
	const { createDefaultChildSessionFactory } = await load("src/runs/shared/child-session.js");
	const { registerRequiredChildExtensions } = await pilotApi(packagePath, "required-child-extensions");
	const sessionId = "guarded-fixture-parent";
	let role: any;
	let runtimeDisposed = 0;
	const events = { emit(name: string, request: any) {
		assert.equal(name, "pi-subagents:runtime-agent-register:v1");
		role = request.definition;
		request.result = { ok: true, registration: { dispose() { runtimeDisposed++; } } };
	} };
	const registration = await registerReviewSession({ events } as any, sessionId, packagePath);
	assert.deepEqual(role, reviewRole());
	let realSession: any;
	let creates = 0;
	let shutdowns = 0;
	let backendCalls = 0;
	let execCalls = 0;
	let childCwdMatches = false;
	let envMatches = false;
	const module = { ...sdk, createAgentSession: async (options: any) => {
		creates++;
		const result = await sdk.createAgentSession(options);
		realSession = result.session;
		return result;
	} };
	const factory = createDefaultChildSessionFactory({ loadPiCodingAgent: async () => module });
	const build = (overrides = {}) => buildInProcessChildLaunch({
		parentSessionId: sessionId, sessionEnabled: false, model: role.model + ":low",
		inheritProjectContext: true, inheritGlobalContext: false, inheritSkills: false,
		tools: role.tools, extensions: [], systemPrompt: role.systemPrompt,
		cwd: fixture, childAgentName: "devflow.review-standards", childIndex: 0, host: "parent",
		projectTrusted: false, allowNestedSubagents: false, waitToolEnabled: false,
		...overrides,
	});
	const base = process.env.DEVFLOW_TEST_BASE!;
	const head = process.env.DEVFLOW_TEST_HEAD!;
	const target = bindReviewTarget(fixture, [base, head, `${base}..${head}`]);
	const launch = build();
	assert.equal(launch.session.cwd, fixture);
	assert.notEqual(fixture, process.cwd());
	assert.equal(launch.session.processEnv, undefined);
	assert.equal(launch.session.ambientExtensions, false);
	assert.equal(launch.session.requiredExtensions.length, 1);
	assert.ok(launch.session.extensionPaths.some((p: string) => p.endsWith("review-child.ts")));
	launch.session.hooks.push({ name: "devflow:test-observer", factory(api: any) {
		api.on("session_start", (_event: any, ctx: any) => {
			childCwdMatches = ctx.cwd === fixture && ctx.cwd !== process.cwd();
			envMatches = process.env.DEVFLOW_BROWSER_ENV === "DEVFLOW_TEST_ENV_ONLY";
		});
		api.on("session_shutdown", () => { shutdowns++; });
		// A restoration call would go through this SDK exec boundary.
		api.exec = async () => { execCalls++; throw new Error("restore запрещён"); };
	} });
	const child = await factory.create(launch.session);
	const matrix: any[] = [];
	try {
		assert.equal(creates, 1);
		assert.deepEqual(child.messages, []);
		assert.equal(execCalls, 0);
		assert.equal(child.modelId, "openai-codex/gpt-6.1-sol");
		assert.equal(realSession.thinkingLevel, "low");
		const runner = realSession.extensionRunner;
		const prompt = await runner.emitBeforeAgentStart({ messageType: "user", prompt: "cwd: fixture; target: HEAD" },
			{ customPrompt: role.systemPrompt, cwd: fixture, selectedTools: role.tools, sections: {} });
		const effective = JSON.stringify(prompt.systemPromptOptions);
		assert.ok(effective.includes("DEVFLOW_TEST_SHARED_INSTRUCTIONS"));
		assert.ok(!effective.includes("PARENT_HISTORY_ONLY"));
		assert.ok(!effective.includes("OTHER_AXIS_ONLY"));
		assert.ok(!effective.includes("devflow_restore"));
		assert.ok(effective.includes("devflow_review_readonly"));
		const invoke = async (toolName: string, input: any, backend?: () => Promise<any>) => {
			const blocked = await runner.emitToolCall({ type: "tool_call", toolCallId: "probe", toolName, input });
			if (blocked?.block) return blocked;
			backendCalls++;
			assert.ok(backend, "запрещённый probe дошёл до backend");
			return backend!();
		};
		const read = sdk.createReadTool(fixture);
		const result = await invoke("read", { path: "safe.txt" }, () => read.execute("read", { path: "safe.txt" }));
		assert.ok(JSON.stringify(result).includes("FIXTURE_CONTENT"));
		const bash = sdk.createBashTool(fixture);
		const status = await invoke("bash", { command: REVIEW_GIT + " status --porcelain=v1 --untracked-files=all --ignore-submodules=all" },
			() => bash.execute("git", { command: REVIEW_GIT + " status --porcelain=v1 --untracked-files=all --ignore-submodules=all" }));
		assert.ok(JSON.stringify(status).includes("untracked.txt"));
		const context = await invoke("bash", { command: "devflow context" },
			() => bash.execute("context", { command: "devflow context" }));
		assert.ok(JSON.stringify(context).includes("guarded-fixture"));
		const before = backendCalls;
		for (const hasUI of [false, true]) {
			const handlers: any[] = [];
			registerReviewChild({ on(name: string, handler: any) {
				if (name === "tool_call") handlers.push(handler);
			} } as any);
			assert.equal(handlers.length, 2);
			const ctx = { cwd: fixture, hasUI, ui: { confirm: async () => true } };
			let matrixBackendCalls = 0;
			const call = async (toolName: string, input: any, allowed: boolean, verb = toolName, expected = "") => {
				const verdicts = [];
				for (const handler of handlers) verdicts.push(await handler({ type: "tool_call", toolCallId: "matrix", toolName, input }, ctx));
				const blocked = verdicts.some(value => value?.block);
				assert.equal(blocked, !allowed, JSON.stringify({ hasUI, toolName, input, verdicts }));
				if (allowed) {
					assert.deepEqual(verdicts, [undefined, undefined]);
					matrixBackendCalls++;
					const result = await bash.execute("matrix", input);
					assert.ok(JSON.stringify(result).includes(expected), JSON.stringify(result));
				}
				matrix.push({ hasUI, kind: allowed ? "allowed" : "denied", verb, input, passed: true });
			};
			for (const [tail, expected] of [
				["status --porcelain=v1 --untracked-files=all --ignore-submodules=all", "untracked.txt"],
				["rev-parse --verify HEAD", head], ["ls-files", "safe.txt"],
				[`show --no-ext-diff --no-textconv ${head} -- safe.txt`, "SECOND_COMMIT"],
				[`diff --no-ext-diff --no-textconv ${base}..${head} -- safe.txt`, "+SECOND_COMMIT"],
			]) await call("bash", { command: `${REVIEW_GIT} ${tail}` }, true, tail.split(" ")[0], expected);
			const tails = [
				"push origin feature", "add safe.txt", "commit -m probe", "reset --hard", "clean -fd", "config core.pager probe",
				"-c core.pager=probe show HEAD", "--paginate show HEAD", "show --ext-diff HEAD", "show --textconv HEAD",
				"diff --ext-diff HEAD", "diff --textconv HEAD", "-C /tmp status", "status --porcelain=v1", "ls-files --others",
				"rev-parse --git-dir", "status && true", "status | true", "status; true", "status > safe.txt", "status < safe.txt",
				"status $(true)", "status `true`", "status\ntrue", "status --help",
				... ["show", "diff"].flatMap(verb => [
					`${verb} --no-ext-diff --no-textconv ${"a".repeat(40)} -- safe.txt`,
					`${verb} --no-ext-diff --no-textconv ${base}..${"a".repeat(40)} -- safe.txt`,
					`${verb} --no-ext-diff --no-textconv HEAD -- safe.txt`,
					`${verb} --no-ext-diff --no-textconv ${head} -- ../safe.txt`,
					`${verb} --no-ext-diff --no-textconv ${head} -- linked.txt`,
					`${verb} --no-ext-diff --no-textconv ${head} -- .env`,
				]),
			];
			for (const tail of tails) await call("bash", { command: `${REVIEW_GIT} ${tail}` }, false);
			for (const command of ["claude --version", "claude-bridge probe", "gh pr create", "devflow start fake", "devflow finish fake --status done", "devflow approve fake", "devflow resume fake", "devflow interrupt fake", "python3 -c pass", "node -e 0", "bash -c true", "env git status", "git status", "echo probe > safe.txt"]) {
				await call("bash", { command }, false);
			}
			for (const path of ["../outside.txt", "linked.txt", "linked-dir/safe.txt", "secrets/token", ".env", "review-conformance.md", "bench/combos/all-fable.json", ".git/config", "state.sqlite", "state.sqlite-wal", "state.sqlite-shm", "guard-denied.txt"]) {
				for (const toolName of ["read", "grep"]) await call(toolName, { path, pattern: "." }, false);
			}
			for (const toolName of ["write", "edit", "subagent", "codemode", "mcp", "unknown", "ls", "find", "grep"]) {
				await call(toolName, { path: ".", pattern: ".", content: "bad" }, false);
			}
			for (const [toolName, path] of [["read", "guard-denied.txt"], ["grep", "guard-denied.txt"],
				["grep", "guard-denied-dir"], ["find", "guard-denied-dir"]]) {
				const input = { path, pattern: "." };
				assert.equal(checkReviewTool({ toolName, input } as any, fixture), undefined);
				const event = { type: "tool_call", toolCallId: "permission-mapping", toolName, input };
				assert.equal(await handlers[0](event, ctx), undefined);
				assert.equal((await handlers[1](event, ctx))?.block, true);
				await call(toolName, input, false);
			}
			assert.equal(matrixBackendCalls, 5);
		}
		for (const command of [
			"claude --version", "claude-bridge probe", "git push origin feature", "gh pr create", "git add safe.txt",
			"devflow finish fake --status done", "devflow start fake", "devflow approve fake", "devflow resume fake",
			"python3 -c pass", "node -e 0", "bash -c true", "env git status", "git -C /tmp status", "git -c core.pager=probe show HEAD",
			REVIEW_GIT + " diff --ext-diff HEAD", REVIEW_GIT + " show --textconv HEAD",
			REVIEW_GIT + " status; true", REVIEW_GIT + " status > safe.txt", "$(true)", "`true`",
		]) assert.equal((await invoke("bash", { command })).block, true, command);
		for (const path of ["../outside.txt", "linked.txt", "linked-dir/safe.txt", "secrets/token", ".env", "review-conformance.md", "bench/combos/all-fable.json", ".git/config", "state.sqlite"]) {
			assert.equal((await invoke("read", { path })).block, true, path);
			assert.equal((await invoke("grep", { path, pattern: "." })).block, true, path);
		}
		for (const toolName of ["write", "edit", "subagent", "codemode", "mcp", "unknown"]) {
			assert.equal((await invoke(toolName, { path: "safe.txt", content: "bad" })).block, true);
		}
		for (const toolName of ["ls", "find", "grep"]) assert.equal((await invoke(toolName, { path: ".", pattern: "." })).block, true);
		// This path passes the strict filter, so the actual Python-backed shared guard must block it.
		assert.equal(checkReviewTool({ toolName: "read", input: { path: "guard-denied.txt" } } as any, fixture), undefined);
		assert.equal((await invoke("read", { path: "guard-denied.txt" })).block, true);
		assert.equal(backendCalls, before);
		const unavailableSpawn = () => {
			const process: any = new EventEmitter();
			process.stdout = new EventEmitter(); process.stderr = { resume() {} };
			process.stdin = Object.assign(new EventEmitter(), { end() { queueMicrotask(() => process.emit("error", new Error("guard unavailable"))); } });
			return process;
		};
		const unavailable = await guardTool({ toolName: "read", input: { path: "safe.txt" } }, { cwd: fixture, hasUI: false } as any,
			(event, cwd) => checkTool(event, cwd, unavailableSpawn as any));
		assert.equal(unavailable.block, true);
		assert.ok(unavailable.reason.includes("недоступна"));
		assert.equal(envMatches, true);
		assert.equal(childCwdMatches, true);
		writeFileSync(join(external, "guarded-context.json"), JSON.stringify({ effective, role, envMatches, childCwdMatches, backendCalls, creates, execCalls }));
	} finally { await child.abort(); await child.dispose(); await factory.dispose(); target.dispose(); }
	assert.equal(shutdowns, 1);
	assert.equal(execCalls, 0);
	assert.throws(() => build({ capabilityCeiling: { denyExtensions: true, sources: [] } }), /required|extension/i);
	registration.dispose(); registration.dispose();
	assert.equal(runtimeDisposed, 1);
	assert.throws(() => registerRequiredChildExtensions({ sessionId, extensions: [{ id: "missing", path: join(external, "missing.ts") }] }), /importable/);
	for (const [name, content] of [
		["load-error", "throw new Error('required load error'); export default function() {}"],
		["startup-error", "export default function(pi) { pi.on('session_start', () => { throw new Error('required startup error'); }); }"],
	]) {
		const path = join(external, name + ".ts"); writeFileSync(path, content);
		const required = registerRequiredChildExtensions({ sessionId, extensions: [{ id: name, path }], requireForAllRunners: true });
		try {
			await assert.rejects(() => factory.create(build().session), /Required child extension failed/);
		} finally { required.dispose(); await factory.dispose(); }
	}
	const missingOwner = { events: { emit() {} } };
	await assert.rejects(() => registerReviewSession(missingOwner as any, sessionId, packagePath), /недоступна/);
	const last = await registerReviewSession({ events } as any, sessionId, packagePath);
	await assert.rejects(() => registerReviewSession({ events } as any, sessionId, packagePath), /already registered/);
	last.dispose();
	writeFileSync(join(external, "guarded-result.json"), JSON.stringify({ guarded: true, creates, shutdowns, runtimeDisposed, backendCalls, execCalls, role, matrix }));
}
