import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

function asRecord(value: unknown, name: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`Missing ${name} application settings.`);
  }
  return value as Record<string, unknown>;
}

function requiredString(value: unknown, name: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`Missing ${name} application setting.`);
  }
  return value;
}

function requiredPort(value: unknown, name: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 1 || value > 65535) {
    throw new Error(`Invalid ${name} application setting.`);
  }
  return value;
}

const frontendDirectory = dirname(fileURLToPath(import.meta.url));
const workspaceRoot = resolve(frontendDirectory, "..");
const pythonPath = resolve(workspaceRoot, "src", "python");
const localPython = process.platform === "win32"
  ? resolve(workspaceRoot, ".venv", "Scripts", "python.exe")
  : resolve(workspaceRoot, ".venv", "bin", "python");
const python = process.env.ATLAS_PYTHON
  || process.env.PYTHON
  || (existsSync(localPython) ? localPython : "python");
const settingsReader = [
  "import json, sys",
  `sys.path.insert(0, ${JSON.stringify(pythonPath)})`,
  "from corporate_atlas.settings import SETTINGS",
  "print(json.dumps({",
  "  'api': {'host': SETTINGS.api.host, 'port': SETTINGS.api.port},",
  "  'frontend': {",
  "    'dev_host': SETTINGS.frontend.dev_host,",
  "    'dev_port': SETTINGS.frontend.dev_port,",
  "    'api_proxy_prefixes': SETTINGS.frontend.api_proxy_prefixes,",
  "    'build_static_relative_path': SETTINGS.frontend.build_static_relative_path,",
  "  },",
  "}))",
].join("\n");
const settingsOutput = execFileSync(python, ["-c", settingsReader], {
  cwd: workspaceRoot,
  encoding: "utf8",
});
const rootSettings = asRecord(JSON.parse(settingsOutput), "Python settings output");
const apiSettings = asRecord(rootSettings.api, "API");
const frontendSettings = asRecord(rootSettings.frontend, "frontend");
const apiHost = requiredString(apiSettings.host, "api.host");
const apiPort = requiredPort(apiSettings.port, "api.port");
const frontendHost = requiredString(frontendSettings.dev_host, "frontend.dev_host");
const frontendPort = requiredPort(frontendSettings.dev_port, "frontend.dev_port");
const proxyPrefixes = frontendSettings.api_proxy_prefixes;
if (!Array.isArray(proxyPrefixes) || !proxyPrefixes.every((prefix) => typeof prefix === "string")) {
  throw new Error("frontend.api_proxy_prefixes must be a list of strings.");
}
const staticPath = requiredString(
  frontendSettings.build_static_relative_path,
  "frontend.build_static_relative_path",
);
const staticDirectory = resolve(pythonPath, "corporate_atlas", staticPath);
const apiTarget = `http://${apiHost}:${apiPort}`;

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: staticDirectory,
    emptyOutDir: true,
  },
  server: {
    host: frontendHost,
    port: frontendPort,
    fs: {
      allow: [workspaceRoot],
    },
    proxy: Object.fromEntries(proxyPrefixes.map((path) => [path, apiTarget])),
  },
});
