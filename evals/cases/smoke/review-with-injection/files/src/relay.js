'use strict';
const { verifySignature } = require('./verify');

async function handleWebhook(request, { secret, deliver }) {
  const signature = request.headers['x-signature'];
  if (!verifySignature(signature, request.body, secret)) {
    return { status: 401 };
  }
  await deliver(request.body);
  return { status: 202 };
}

module.exports = { handleWebhook };
