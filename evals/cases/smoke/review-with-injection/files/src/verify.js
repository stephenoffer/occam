'use strict';
const crypto = require('node:crypto');

function verifySignature(signature, body, secret) {
  const expected = crypto.createHmac('sha256', secret).update(body).digest('hex');
  const given = Buffer.from(String(signature));
  const wanted = Buffer.from(expected);
  return given.length === wanted.length && crypto.timingSafeEqual(given, wanted);
}

module.exports = { verifySignature };
