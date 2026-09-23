const path = require("path");

/**
 * Format a display name.
 */
function formatName(first, last = "", ...extra) {
  return [first, last, ...extra].join(" ").trim();
}

function initials(name) {
  return formatName(name).slice(0, 2);
}

module.exports = { formatName, initials };
