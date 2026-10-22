import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import devflow from '../../pi/extensions/devflow.ts';

function harness(t, provider = 'anthropic') {
  const dir = mkdtempSync(join(tmpdir(), 'devflow-entry-'));
  const path = join(dir, 'rules.md');
  writeFileSync(path, 'Общая редакция A');
  const old = process.env.DEVFLOW_INSTRUCTIONS;
  process.env.DEVFLOW_INSTRUCTIONS = path;
  t.after(() => {
    if (old === undefined) delete process.env.DEVFLOW_INSTRUCTIONS;
    else process.env.DEVFLOW_INSTRUCTIONS = old;
    rmSync(dir, { recursive: true });
  });
  const handlers = {};
  const notices = [];
  let aborted = 0, shutdown = 0;
  const ctx = {
    model: { provider, id: 'test' }, hasUI: true,
    ui: { notify: text => notices.push(text) },
    abort: () => aborted++, shutdown: () => shutdown++,
  };
  const pi = {
    on: (event, handler) => { assert.equal(handlers[event], undefined); handlers[event] = handler; },
    setModel: async model => { ctx.model = model; return true; },
  };
  devflow(pi);
  return { handlers, pi, ctx, notices, path, counts: () => ({ aborted, shutdown }) };
}

test('драйвер и фаза читают одну редакцию; повтор, reload и new не накапливают разделы', async t => {
  const h = harness(t);
  const event = { systemPromptOptions: { sections: { project: 'Проект' } } };
  for (let i = 0; i < 3; i++) {
    await h.handlers.session_start({}, h.ctx);
    await h.handlers.before_agent_start(event, h.ctx);
  }
  assert.deepEqual(Object.keys(event.systemPromptOptions.sections).sort(), ['devflow_host', 'devflow_shared', 'project']);
  assert.equal(event.systemPromptOptions.sections.devflow_shared, 'Общая редакция A');
  writeFileSync(h.path, 'Общая редакция B');
  await h.handlers.before_agent_start(event, h.ctx);
  const phase = harness(t);
  // Отдельный процесс получает тот же глобальный путь, не копию текста от launcher.
  process.env.DEVFLOW_INSTRUCTIONS = h.path;
  const phaseEvent = { systemPromptOptions: { sections: {} } };
  await phase.handlers.before_agent_start(phaseEvent, phase.ctx);
  assert.equal(phaseEvent.systemPromptOptions.sections.devflow_shared, event.systemPromptOptions.sections.devflow_shared);
  const reloaded = {};
  devflow({ ...h.pi, on: (name, handler) => { reloaded[name] = handler; } });
  await reloaded.before_agent_start(event, h.ctx);
  assert.equal(Object.keys(event.systemPromptOptions.sections).length, 3);
  assert.deepEqual(h.counts(), { aborted: 0, shutdown: 0 });
});

test('bridge на старте останавливает сессию, прямой Anthropic разрешён', async t => {
  const h = harness(t, 'claude-bridge');
  await h.handlers.session_start({}, h.ctx);
  await h.handlers.before_agent_start({ systemPromptOptions: { sections: {} } }, h.ctx);
  assert.deepEqual(h.counts(), { aborted: 2, shutdown: 2 });
  assert.match(h.notices[0], /claude-bridge/);
  h.ctx.model = { provider: 'anthropic' };
  await h.handlers.session_start({}, h.ctx);
  assert.deepEqual(h.counts(), { aborted: 2, shutdown: 2 });
});

test('смена модели на bridge отменяет работу и возвращает предыдущую модель', async t => {
  const h = harness(t, 'claude-bridge');
  await h.handlers.model_select({ model: h.ctx.model, previousModel: { provider: 'openai-codex' } }, h.ctx);
  assert.equal(h.ctx.model.provider, 'openai-codex');
  assert.deepEqual(h.counts(), { aborted: 1, shutdown: 0 });
  h.pi.setModel = async () => false;
  await h.handlers.model_select({ model: { provider: 'claude-bridge' }, previousModel: { provider: 'anthropic' } }, h.ctx);
  assert.equal(h.counts().shutdown, 1);
});

test('отсутствующие или пустые правила не дают тихо продолжить', async t => {
  const h = harness(t);
  writeFileSync(h.path, '');
  await h.handlers.before_agent_start({ systemPromptOptions: { sections: {} } }, h.ctx);
  rmSync(h.path);
  await h.handlers.session_start({}, h.ctx);
  assert.deepEqual(h.counts(), { aborted: 2, shutdown: 2 });
});
