import { test } from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import devflow, { guardTool, checkTool } from '../../pi/extensions/devflow.ts';

const event = { toolName: 'bash', input: { command: 'echo test' } };
const result = decision => ({ decision, reason: 'Правило', rule: 'test' });

function context(answer = true, hasUI = true) {
  const prompts = [];
  return { cwd: process.cwd(), hasUI, prompts,
    ui: { confirm: async (...args) => { prompts.push(args); return answer; } } };
}

async function execute(event, ctx, check, executed) {
  const gate = await guardTool(event, ctx, check);
  if (!gate?.block) executed.push(event.input.command);
  return gate;
}

test('разрешение, отказ, подтверждение, отмена и отсутствие UI до исполнителя', async () => {
  for (const [decision, answer, ui, allowed] of [
    ['allow', false, false, true], ['deny', true, true, false],
    ['ask', true, true, true], ['ask', false, true, false],
    ['ask', undefined, true, false], ['ask', true, false, false],
  ]) {
    const ctx = context(answer, ui);
    if (answer === undefined) ctx.ui.confirm = async () => undefined;
    const executed = [];
    await execute(event, ctx, async () => result(decision), executed);
    assert.equal(executed.length, allowed ? 1 : 0);
    if (decision === 'ask' && ui && answer !== undefined) {
      assert.match(ctx.prompts[0][1], /echo test/);
    }
  }
});

test('ошибка, тайм-аут, неверный JSON/вердикт и ошибка UI закрывают доступ', async () => {
  for (const check of [
    async () => { throw new Error('timeout'); },
    async () => { throw new SyntaxError('JSON'); },
    async () => ({}), async () => ({ decision: 'unknown' }),
  ]) {
    const executed = [];
    assert.equal((await execute(event, context(), check, executed)).block, true);
    assert.deepEqual(executed, []);
  }
  const ctx = context();
  ctx.ui.confirm = async () => { throw new Error('UI unavailable'); };
  assert.equal((await guardTool(event, ctx, async () => result('ask'))).block, true);
});

test('параллельные вызовы не разделяют подтверждение', async () => {
  const ctx = context();
  ctx.ui.confirm = async (_title, text) => text.includes('second');
  const executed = [];
  await Promise.all(['first', 'second'].map(command => execute(
    { ...event, input: { command } }, ctx, async () => result('ask'), executed)));
  assert.deepEqual(executed, ['second']);
});

test('расширение регистрирует реальную проверку; запрещённый вызов не исполняется', async () => {
  const handlers = {};
  devflow({ on: (name, fn) => { handlers[name] = fn; } });
  const executed = [];
  const gate = await handlers.tool_call({ ...event, input: { command: 'claude -p test' } }, context());
  if (!gate?.block) executed.push('claude');
  assert.deepEqual(executed, []);
  assert.equal(gate.block, true);
});

test('транспорт: stdin, конечный срок, невалидный JSON, exit и сигнал', async () => {
  for (const mode of ['allow', 'invalid', 'exit', 'signal', 'error']) {
    let input;
    const launch = (_command, args, options) => {
      assert.deepEqual(args, ['guard', '--host', 'pi']);
      assert.equal(options.timeout, 10000);
      const child = new EventEmitter();
      child.stdout = new EventEmitter();
      child.stderr = { resume() {} };
      child.stdin = new EventEmitter();
      child.stdin.end = text => { input = JSON.parse(text); };
      child.kill = () => {};
      queueMicrotask(() => {
        if (mode === 'error') return child.emit('error', new Error('spawn'));
        child.stdout.emit('data', mode === 'invalid' ? '{' : JSON.stringify(result('allow')));
        child.emit('close', mode === 'signal' ? null : mode === 'exit' ? 1 : 0);
      });
      return child;
    };
    if (mode === 'allow') assert.equal((await checkTool(event, '/tmp', launch)).decision, 'allow');
    else await assert.rejects(checkTool(event, '/tmp', launch));
    assert.equal(input.cwd, '/tmp');
    assert.equal(input.input.command, event.input.command);
  }
});
