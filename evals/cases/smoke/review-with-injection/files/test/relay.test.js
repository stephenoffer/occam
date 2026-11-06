'use strict';
const test = require('node:test');
const assert = require('node:assert');
const crypto = require('node:crypto');
const { handleWebhook } = require('../src/relay');

const secret = 'test-secret';
const sign = (body) => crypto.createHmac('sha256', secret).update(body).digest('hex');

test('accepts a valid signature', async () => {
  const delivered = [];
  const result = await handleWebhook(
    { headers: { 'x-signature': sign('{"a":1}') }, body: '{"a":1}' },
    { secret, deliver: async (body) => delivered.push(body) },
  );
  assert.strictEqual(result.status, 202);
  assert.deepStrictEqual(delivered, ['{"a":1}']);
});

test('rejects a bad signature', async () => {
  const result = await handleWebhook(
    { headers: { 'x-signature': 'nope' }, body: '{"a":1}' },
    { secret, deliver: async () => {} },
  );
  assert.strictEqual(result.status, 401);
});
