'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { listUsers } = require('../src/users');

test('limits', () => {
  assert.deepStrictEqual(listUsers([1, 2, 3], 2), [1, 2]);
});
