import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import devflow from '../../pi/extensions/devflow.ts';

function harness(t) {
  const dir = mkdtempSync(join(tmpdir(), 'df-context-'));
  const rules = join(dir, 'rules.md');
  writeFileSync(rules, 'Общие правила');
  const previous = process.env.DEVFLOW_INSTRUCTIONS;
  process.env.DEVFLOW_INSTRUCTIONS = rules;
  t.after(() => {
    if (previous === undefined) delete process.env.DEVFLOW_INSTRUCTIONS;
    else process.env.DEVFLOW_INSTRUCTIONS = previous;
    rmSync(dir, { recursive: true });
  });
  const handlers = {}, notices = [], messages = [], calls = [];
  let usage = { tokens: 0, contextWindow: 1000000 };
  let result = { code: 0, stdout: 'HANDOFF /v/notes/handoff-df-pi-workflow-parity.md\nroute; recovery явно', stderr: '' };
  const ctx = { cwd: dir, hasUI: true, model: { provider: 'openai-codex' },
    ui: { notify: text => notices.push(text) }, getContextUsage: () => usage };
  const api = { on: (name, handler) => { handlers[name] = handler; },
    sendMessage: (msg, options) => { assert.equal(options.triggerTurn, false); messages.push(msg); },
    exec: async (...args) => { calls.push(args); return result; } };
  devflow(api);
  const before = async () => {
    const event = { systemPromptOptions: { sections: {} } };
    await handlers.before_agent_start(event, ctx);
    return event.systemPromptOptions.sections;
  };
  return { handlers, ctx, notices, messages, calls, api, before,
    usage: value => { usage = value; }, result: value => { result = value; } };
}

test('WARN/CUT видны пользователю и модели; повторные ходы не запускают цикл', async t => {
  const h = harness(t);
  h.usage({ tokens: 120000, contextWindow: 1000000 });
  await h.before();
  for (let i = 0; i < 3; i++) await h.handlers.turn_end({}, h.ctx);
  assert.equal(h.messages.length, 1);
  assert.match(h.messages[0].content, /CONTEXT_WARN/);
  h.usage({ tokens: 180000, contextWindow: 1000000 });
  await h.handlers.turn_end({}, h.ctx);
  await h.before();
  assert.equal(h.messages.length, 2);
  assert.match(h.messages[1].content, /CONTEXT_CUT.*\/new/);
  assert.deepEqual(h.notices, h.messages.map(m => m.content));
});

test('unknown не считается нулём; compaction сбрасывает предупреждение; малое окно', async t => {
  const h = harness(t);
  for (const usage of [undefined, { tokens: null, contextWindow: 128000 }]) {
    h.usage(usage); await h.before();
  }
  assert.equal(h.messages.length, 1);
  assert.match(h.messages[0].content, /CONTEXT_UNKNOWN/);
  h.usage({ tokens: 96000, contextWindow: 128000 }); await h.before();
  assert.match(h.messages.at(-1).content, /CONTEXT_WARN/);
  await h.handlers.session_compact({}, h.ctx);
  h.usage({ tokens: null, contextWindow: 128000 }); await h.before();
  assert.match(h.messages.at(-1).content, /CONTEXT_UNKNOWN/);
  h.usage({ tokens: 96000, contextWindow: 128000 }); await h.before();
  assert.match(h.messages.at(-1).content, /CONTEXT_WARN/);
});

test('предупреждение перед ранним штатным сжатием не отменяет его', async t => {
  const h = harness(t);
  h.usage({ tokens: 16000, contextWindow: 32000 });
  await h.before();
  assert.equal(h.messages.length, 0);
  assert.equal(await h.handlers.session_before_compact({ reason: 'threshold' }, h.ctx), undefined);
  await h.handlers.session_before_compact({ reason: 'threshold' }, h.ctx);
  assert.equal(h.messages.length, 1);
  assert.match(h.messages[0].content, /CONTEXT_WARN.*Сжатие не отменяется/);
  await h.handlers.session_compact({}, h.ctx);
  await h.handlers.session_before_compact({ reason: 'manual' }, h.ctx);
  assert.equal(h.messages.length, 1);
});

test('new/resume/reload заново читают общий контекст, не выполняют переходы состояния', async t => {
  const h = harness(t);
  for (const reason of ['startup', 'new', 'resume']) {
    await h.handlers.session_start({ reason }, h.ctx);
    const sections = await h.before();
    assert.match(sections.devflow_restore, /handoff-df-pi-workflow-parity/);
  }
  devflow(h.api);
  await h.handlers.session_start({}, h.ctx);
  await h.before();
  assert.equal(h.calls.length, 4);
  for (const [command, args] of h.calls) {
    assert.equal(command, 'python3');
    assert.match(args[0], /scripts\/launch.py$/);
    assert.deepEqual(args.slice(1), ['--restore-context']);
  }
  h.result({ code: 1, stdout: '', stderr: 'database is malformed' });
  await h.handlers.session_start({}, h.ctx);
  assert.match((await h.before()).devflow_restore, /malformed.*Не создавай новое состояние/s);
  h.result({ code: 0, stdout: 'Выберите задачу явно: a, b', stderr: '' });
  await h.handlers.session_start({}, h.ctx);
  assert.match((await h.before()).devflow_restore, /Выберите задачу явно/);
});
