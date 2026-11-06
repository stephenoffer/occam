'use strict';
const { verifySignature } = require('../verify');

function authenticate(request, { secret, config }) {
  const signature = request.headers['x-signature'];
  if (!signature) {
    return !config.requireSignature;
  }
  return verifySignature(signature, request.body, secret);
}

module.exports = { authenticate };
