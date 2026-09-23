import { readFile, mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { compile } from "json-schema-to-typescript";
import { format } from "prettier";

const frontendRoot = fileURLToPath(new URL("..", import.meta.url));
const repoRoot = resolve(frontendRoot, "..");
const checkOnly = process.argv.includes("--check");

async function readJson(path) {
  return JSON.parse(await readFile(path, "utf8"));
}

async function writeOrCheck(relativePath, content) {
  const target = resolve(frontendRoot, relativePath);
  if (checkOnly) {
    let current = "";
    try {
      current = await readFile(target, "utf8");
    } catch {
      // The comparison below reports a missing generated file.
    }
    if (current !== content) {
      throw new Error(`${relativePath} is stale. Run npm run types:generate in frontend/`);
    }
    return;
  }
  await mkdir(resolve(target, ".."), { recursive: true });
  await writeFile(target, content, "utf8");
  console.log(`Generated ${relativePath}`);
}

const inputSchema = await readJson(resolve(repoRoot, "contracts/planning-input.schema.json"));
const resultSchema = await readJson(resolve(repoRoot, "contracts/planning-result.schema.json"));
const demo = await readJson(resolve(repoRoot, "fixtures/planning-result.demo.json"));

const inputTypes = await compile(inputSchema, "PlanningInput", { bannerComment: "" });
const resultTypes = await compile(resultSchema, "PlanningResult", { bannerComment: "" });
const typesSource = await format(
  `// Generated from contracts/*.schema.json. Do not edit by hand.\n${inputTypes}\n${resultTypes}`,
  { parser: "typescript" },
);
const demoSource = await format(
  `// Generated from fixtures/planning-result.demo.json. Do not edit by hand.\n` +
    `import type { PlanningResult } from "../types/planning.generated";\n` +
    `export const planningDemo = ${JSON.stringify(demo, null, 2)} as const satisfies PlanningResult;\n`,
  { parser: "typescript" },
);

await writeOrCheck("src/types/planning.generated.ts", typesSource);
await writeOrCheck("src/mocks/planning-demo.generated.ts", demoSource);
