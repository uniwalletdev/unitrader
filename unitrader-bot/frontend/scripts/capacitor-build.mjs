import fs from "node:fs";
import path from "node:path";
import { execSync } from "node:child_process";

const root = process.cwd();
const appDir = path.join(root, "app");
const disabledDir = path.join(root, "_app_capacitor_disabled");
const nextDir = path.join(root, ".next");

function exists(p) {
  try {
    fs.accessSync(p);
    return true;
  } catch {
    return false;
  }
}

function move(from, to) {
  try {
    fs.renameSync(from, to);
  } catch (e) {
    // Windows can throw EPERM if directory is locked; fall back to copy+remove.
    fs.cpSync(from, to, { recursive: true, force: true });
    fs.rmSync(from, { recursive: true, force: true });
  }
}

const hadApp = exists(appDir);
if (exists(nextDir)) {
  fs.rmSync(nextDir, { recursive: true, force: true });
}
if (hadApp) {
  if (exists(disabledDir)) {
    throw new Error("Found _app_capacitor_disabled already; aborting.");
  }
  move(appDir, disabledDir);
}

try {
  execSync("next build", {
    stdio: "inherit",
    env: { ...process.env, CAPACITOR: "true" },
  });
} finally {
  if (hadApp && exists(disabledDir) && !exists(appDir)) {
    move(disabledDir, appDir);
  }
}

