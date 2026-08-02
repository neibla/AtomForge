import { execFileSync } from "node:child_process";
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";

const roots = ["src/api/default", "src/api/model"];
const files = (root) =>
  readdirSync(root, { withFileTypes: true }).flatMap((entry) => {
    const path = join(root, entry.name);
    return entry.isDirectory() ? files(path) : [path];
  });
const snapshot = () =>
  new Map(
    roots.flatMap(files).map((path) => [relative(process.cwd(), path), readFileSync(path)]),
  );

const before = snapshot();
execFileSync("bun", ["run", "api:generate"], { stdio: "inherit" });
const after = snapshot();
if (
  before.size !== after.size ||
  [...before].some(([path, content]) => !after.has(path) || !content.equals(after.get(path)))
) {
  throw new Error("Generated API output is not stable; regenerate and commit the result.");
}
