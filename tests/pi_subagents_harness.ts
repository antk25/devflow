import assert from "node:assert/strict";
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { EventEmitter } from "node:events";
import * as sdk from "@earendil-works/pi-coding-agent";
import { checkTool, guardTool } from "../pi/extensions/devflow.ts";
import { REVIEW_GIT, bindReviewTarget, checkReviewTool, registerReviewChild } from "../pi/pilots/review-child.ts";
import reviewStandards, { pilotApi, registerReviewSession, reviewRole, reduceReview, settleReview,
	unavailableReview, saveReviewEvidence, REVIEW_MODEL } from "../pi/pilots/review-standards.ts";

async function interactiveProbe() {
	const external = process.env.DEVFLOW_TEST_EVIDENCE!;
	const packagePath = process.env.DEVFLOW_SUBAGENTS_PILOT_PACKAGE!;
	const rows: any[] = [];
	const commands = new Map<string, any>();
	const notices: string[] = [];
	const calls = { delegation: 0, provider: 0, child: 0, backend: 0 };
	const api: any = { on() {}, registerCommand(name: string, command: any) { commands.set(name, command); },
		events: { emit() { calls.delegation++; throw new Error("delegation forbidden"); },
			on() { throw new Error("subscription forbidden"); } },
		exec() { calls.backend++; throw new Error("backend forbidden"); } };
	reviewStandards(api);
	assert.equal(commands.size, 1);
	for (const target of ["a".repeat(40), "a..b", "--uncommitted", "", "$(forbidden)"]) {
		await commands.get("devflow-review-standards").handler(target, new Proxy({
			ui: { notify(message: string) { notices.push(message); } },
		}, { get(context, key) {
			if (key === "ui") return context.ui;
			if (key === "modelRegistry" || key === "modelRuntime") calls.provider++;
			else calls.backend++;
			throw new Error(`NO-GO must not access context.${String(key)}`);
		} }));
		assert.ok(notices.at(-1)!.includes("unavailable/lifecycle_unverifiable"));
		rows.push({ name: `command:${target}`, passed: true });
	}
	assert.deepEqual(calls, { delegation: 0, provider: 0, child: 0, backend: 0 });
	commands.clear();
	const enabled = process.env.DEVFLOW_SUBAGENTS_PILOT_PACKAGE;
	try {
		delete process.env.DEVFLOW_SUBAGENTS_PILOT_PACKAGE;
		reviewStandards(api);
		assert.equal(commands.size, 0);
	} finally { process.env.DEVFLOW_SUBAGENTS_PILOT_PACKAGE = enabled; }
	rows.push({ name: "without-opt-in", passed: true });

	const identity = { requestId: "attempt", ownerRunId: "owner", nodeId: "leaf" };
	const initial = () => ({ ...unavailableReview(), identity, taskStatus: "pending", outcome: "pending", final: false });
	const terminal = { status: "completed", model: REVIEW_MODEL, thinking: "low", exitCode: 0, text: "synthetic only" };
	const signal = (data: any) => ({ ...identity, ...data });
	for (const status of ["completed", "cancelled", "timed_out", "failed", "interrupted"]) {
		for (const shutdown of [undefined, false, true]) for (const noWork of [undefined, false, true]) {
			const result = settleReview(status, shutdown, noWork);
			assert.equal(result.outcome, shutdown === true && noWork === true ? status : "unavailable");
			let state = reduceReview(initial(), signal({ kind: "terminal", terminal: { ...terminal, status } }), 0);
			state = reduceReview(state, signal({ kind: "cleanup", shutdownConfirmed: shutdown,
				noActiveWorkConfirmed: noWork }), 1);
			assert.equal(state.outcome, result.outcome);
			assert.equal(state.final, result.outcome !== "unavailable");
			if (!state.final) {
				state = reduceReview(state, signal({ kind: "tick" }), 10000);
				assert.equal(state.reason, "cleanup_unconfirmed");
				assert.equal(state.originalReason, status);
			}
			rows.push({ name: `settle:${status}:${shutdown}:${noWork}`, passed: true });
		}
	}
	for (const [name, patch, expected] of [
		["success-synthetic-only", {}, "completed"], ["empty", { text: " " }, "empty_response"],
		["model-unknown", { model: undefined }, "failed"], ["thinking-unknown", { thinking: undefined }, "failed"],
		["exit-error", { exitCode: 1 }, "failed"], ["partial", { status: "failed", text: "partial" }, "failed"],
	] as const) {
		let state = reduceReview(initial(), signal({ kind: "terminal", terminal: { ...terminal, ...patch } }), 50);
		assert.equal(state.outcome, "unavailable");
		state = reduceReview(state, signal({ kind: "cleanup", shutdownConfirmed: true, noActiveWorkConfirmed: true }), 51);
		assert.equal(state.outcome, expected);
		assert.equal(state.final, true);
		rows.push({ name, passed: true });
	}
	for (const first of ["terminal", "cancel"]) {
		let state = reduceReview(initial(), signal({ kind: first, terminal }), 100);
		assert.equal(state.deadline, 10100);
		const same = state;
		for (const field of ["requestId", "ownerRunId", "nodeId"]) {
			assert.equal(reduceReview(state, signal({ kind: "cleanup", [field]: "foreign", shutdownConfirmed: true,
				noActiveWorkConfirmed: true }), 101), same);
		}
		if (first === "terminal") {
			const duplicate = reduceReview(state, signal({ kind: "terminal", terminal: { ...terminal, status: "failed" } }), 101);
			assert.deepEqual(duplicate.terminal, terminal);
			assert.equal(duplicate.taskStatus, "completed");
		}
		state = reduceReview(state, signal({ kind: "cleanup", disposeResolved: true }), 102);
		assert.equal(state.outcome, "unavailable");
		state = reduceReview(state, signal({ kind: "terminal", terminal }), 200);
		assert.equal(state.deadline, 10100);
		state = reduceReview(state, signal({ kind: "tick" }), 10099);
		assert.equal(state.final, false);
		state = reduceReview(state, signal({ kind: "tick" }), 10100);
		assert.equal(state.reason, "cleanup_unconfirmed");
		assert.equal(state.originalReason, first === "cancel" ? "cancelled" : "completed");
		for (const kind of ["cleanup", "terminal", "cancel", "tick"]) {
			assert.equal(reduceReview(state, signal({ kind, terminal, shutdownConfirmed: true, noActiveWorkConfirmed: true }), 10101), state);
		}
		saveReviewEvidence(state);
		rows.push({ name: `fake-clock:${first}:10000ms:late-foreign-duplicate`, passed: true });
	}
	let failedShutdown = reduceReview(initial(), signal({ kind: "terminal", terminal }), 0);
	failedShutdown = reduceReview(failedShutdown, signal({ kind: "cleanup", shutdownConfirmed: false, noActiveWorkConfirmed: true }), 1);
	failedShutdown = reduceReview(failedShutdown, signal({ kind: "cleanup", shutdownConfirmed: true }), 2);
	assert.equal(failedShutdown.outcome, "unavailable");
	assert.equal(reduceReview(failedShutdown, signal({ kind: "tick" }), 10000).reason, "cleanup_unconfirmed");
	rows.push({ name: "shutdown-error-is-not-ack", passed: true });

	const load = (path: string) => import(pathToFileURL(join(packagePath, path)).href);
	const { createDefaultChildSessionFactory } = await load("src/runs/shared/child-session.js");
	const { toSubagentDelegationResponse } = await load("src/slash/delegation-adapters.js");
	let release!: () => void;
	let shutdownFinished = false;
	let disposed = false;
	const held = new Promise<void>(resolve => { release = resolve; });
	let shutdownDone: Promise<void> | undefined;
	const shutdown = () => shutdownDone = held.then(() => { shutdownFinished = true; });
	const errors: any[] = [];
	const fakeSDK = {
		ModelRuntime: { create: async () => ({}) }, SettingsManager: { create: () => ({}) },
		DefaultResourceLoader: class { loaded = false; reload() {} getExtensions() { return { errors: [], runtime: {} }; } },
		SessionManager: { inMemory: () => ({}) },
		createAgentSession: async () => ({ session: { bindExtensions: async () => {},
			extensionRunner: { hasHandlers: () => true, emit: shutdown },
			dispose() { disposed = true; }, abort: async () => {} } }),
	};
	const factory = createDefaultChildSessionFactory({ loadPiCodingAgent: async () => fakeSDK, shutdownTimeoutMs: 1 });
	const keepAlive = setInterval(() => {}, 1000);
	try {
		const child = await factory.create({ cwd: external, tools: ["read"], extensionPaths: [], hooks: [],
			runtime: {}, storage: { kind: "memory" }, onExtensionError: (error: any) => errors.push(error) });
		await child.dispose();
		await factory.dispose();
		assert.equal(disposed, true);
		assert.equal(shutdownFinished, false);
		assert.deepEqual(errors, []);
		const response = toSubagentDelegationResponse({ ...identity, result: { kind: "text" } },
			{ details: { results: [{ finalOutput: "synthetic", model: REVIEW_MODEL, thinking: "low", exitCode: 0 }] } }, false);
		assert.equal(response.status, "completed");
		let state = reduceReview(initial(), signal({ kind: "terminal", terminal: { ...terminal, status: response.status } }), 0);
		state = reduceReview(state, signal({ kind: "cleanup", disposeResolved: true }), 1);
		assert.equal(state.outcome, "unavailable");
		assert.notEqual(settleReview("cancelled", undefined, undefined).outcome, "cancelled");
		saveReviewEvidence(state);
		writeFileSync(join(external, "factory-result.json"), JSON.stringify({ disposeResolved: true, shutdownFinished,
			errors, syntheticTerminal: response.status, realModelSession: false, outcome: state.outcome }));
		rows.push({ name: "real-factory-fake-sdk-held-shutdown", passed: true });
	} finally {
		release();
		clearInterval(keepAlive);
		await shutdownDone;
		assert.equal(shutdownFinished, true);
	}
	writeFileSync(join(external, "interactive-result.json"), JSON.stringify({ rows, calls, realModelSession: false }));
}


export default async function () {
	if (process.env.DEVFLOW_TEST_INTERACTIVE) return interactiveProbe();
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
