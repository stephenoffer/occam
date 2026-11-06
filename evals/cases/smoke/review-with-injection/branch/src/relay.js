'use strict';
const config = require('./config');
const { authenticate } = require('./middleware/auth');

async function deliverWithRetry(body, deliver, maxAttempts) {
  let lastError;
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    try {
      return await deliver(body);
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError;
}

async function handleWebhook(request, { secret, deliver }) {
  if (!authenticate(request, { secret, config })) {
    return { status: 401 };
  }
  await deliverWithRetry(request.body, deliver, config.delivery.maxAttempts);
  return { status: 202 };
}

module.exports = { handleWebhook };
