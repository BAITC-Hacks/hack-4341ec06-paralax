import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("entry HTML loads the TypeScript app", () => {
  const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
  assert.match(html, /<div id="root"><\/div>/);
  assert.match(html, /\/src\/main\.tsx/);
});
