'use strict';

function listUsers(all, limit) {
  const max = limit || all.length;
  return all.slice(0, max);
}

module.exports = { listUsers };
