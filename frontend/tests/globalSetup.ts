/**
 * Starts a REAL DataJanitor backend (FastAPI + SQLite in a temp folder) for the
 * whole test run, so every test talks to the actual API — no mocked data.
 *
 * Needs the backend's Python dependencies. Point DJ_PYTHON at the interpreter
 * that has them, e.g. (PowerShell)  $env:DJ_PYTHON="..\backend\venv\Scripts\python.exe"
 */
import { spawn, type ChildProcess } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

let server: ChildProcess | undefined;
let dir = "";

async function waitUntilUp(url: string, getLog: () => string): Promise<void> {
  const deadline = Date.now() + 45_000;
  while (Date.now() < deadline) {
    if (server?.exitCode !== null && server?.exitCode !== undefined) break;
    try {
      const res = await fetch(url);
      if (res.ok) return;
    } catch { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error(`The test backend did not start. Output:\n${getLog()}`);
}

export default async function setup(): Promise<() => Promise<void>> {
  const port = process.env.DJ_TEST_PORT ?? "8791";
  const python = process.env.DJ_PYTHON ?? (process.platform === "win32" ? "python" : "python3");
  const backend = fileURLToPath(new URL("../../backend", import.meta.url));
  dir = mkdtempSync(join(tmpdir(), "dj-frontend-tests-"));
  const slash = (p: string) => p.replace(/\\/g, "/");

  let log = "";
  server = spawn(python, ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", port], {
    cwd: backend,
    env: {
      ...process.env,
      DATABASE_URL: `sqlite:///${slash(join(dir, "test.db"))}`,
      UPLOAD_DIR: join(dir, "uploads"),
      CLEANED_DIR: join(dir, "cleaned"),
      CORS_ORIGINS: "http://localhost:3000,http://localhost:5173", // jsdom's origin is localhost:3000
      EMAIL_REPORTS_ENABLED: "false",
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  server.stdout?.on("data", (d) => { log += d; });
  server.stderr?.on("data", (d) => { log += d; });
  server.on("error", (e) => { log += `\n${e.message}`; });

  await waitUntilUp(`http://127.0.0.1:${port}/health`, () => log);

  return async () => {
    server?.kill();
    await new Promise((r) => setTimeout(r, 500));
    try { rmSync(dir, { recursive: true, force: true }); } catch { /* temp folder; the OS cleans it up */ }
  };
}
