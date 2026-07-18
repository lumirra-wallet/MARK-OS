#!/usr/bin/env node
"use strict";

// Cross-platform preinstall check — Windows Command Prompt and PowerShell
// don't provide `sh`, so this must be plain Node with no shell dependency.
// Same behavior as the old `sh -c '...'` script: always remove stray
// lockfiles from other package managers, then require pnpm.
//
// Shared by every package.json that needs this check (currently the repo
// root and workspace/), each pointing at this one file via a relative
// path (e.g. workspace/package.json uses "node ../preinstall.cjs") rather
// than keeping a duplicate copy. Lockfiles are resolved against
// process.cwd(), not this file's own directory — npm/pnpm always run
// lifecycle scripts with cwd set to the package that declared them, so
// this correctly cleans up each package's own directory regardless of
// where the script file physically lives.

const fs = require("fs");
const path = require("path");

for (const lockfile of ["package-lock.json", "yarn.lock"]) {
  fs.rmSync(path.join(process.cwd(), lockfile), { force: true });
}

const userAgent = process.env.npm_config_user_agent || "";
if (!userAgent.startsWith("pnpm/")) {
  console.error("Use pnpm instead");
  process.exit(1);
}
