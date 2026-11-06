'use strict';

const flag = (name) => process.env[name] === 'true';

module.exports = {
  maxBodyBytes: 1_000_000,
  delivery: { maxAttempts: Number(process.env.DELIVERY_MAX_ATTEMPTS || 3) },
  // Lets ops stage the proxy migration in #412 without a deploy.
  requireSignature: flag('REQUIRE_SIGNATURE'),
};
