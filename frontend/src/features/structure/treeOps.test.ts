import { describe, expect, it } from "vitest";

import { indent, moveDown, moveUp, outdent, type Node } from "./treeOps";

// Integration ─┬─ Parts
//              └─ Substitution
// Series
const tree: Node[] = [
  { id: "integration", children: [{ id: "parts" }, { id: "substitution" }] },
  { id: "series" },
];

describe("tree moves", () => {
  it("moves within siblings, and not past either end", () => {
    expect(moveUp(tree, "series")).toEqual({ parent_id: null, position: 0 });
    expect(moveDown(tree, "parts")).toEqual({ parent_id: "integration", position: 1 });
    expect(moveUp(tree, "integration")).toBeUndefined();
    expect(moveDown(tree, "series")).toBeUndefined();
  });

  it("indents under the previous sibling, as its last child", () => {
    expect(indent(tree, "series")).toEqual({ parent_id: "integration", position: 2 });
    expect(indent(tree, "substitution")).toEqual({ parent_id: "parts", position: 0 });
    expect(indent(tree, "integration")).toBeUndefined(); // nothing above it
  });

  it("outdents to just after the parent", () => {
    expect(outdent(tree, "parts")).toEqual({ parent_id: null, position: 1 });
    expect(outdent(tree, "series")).toBeUndefined(); // already top level
  });

  it("returns undefined for unknown ids", () => {
    expect(moveUp(tree, "missing")).toBeUndefined();
  });
});
