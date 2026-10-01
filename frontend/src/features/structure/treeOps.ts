/**
 * Keyboard-friendly tree moves (up, down, indent, outdent) expressed as the
 * single `move` call the API takes: a new parent and a position among the
 * new siblings. Pure functions, so the rules are unit-tested.
 */

export interface Node {
  id: string;
  children?: Node[];
}

export interface Move {
  parent_id: string | null;
  position: number;
}

interface Located {
  parentId: string | null;
  siblings: Node[];
  index: number;
  grandparent?: Located;
}

export function locate(tree: Node[], id: string, parentId: string | null = null, parent?: Located): Located | undefined {
  for (const [index, node] of tree.entries()) {
    const here: Located = { parentId, siblings: tree, index, grandparent: parent };
    if (node.id === id) return here;
    const found = locate(node.children ?? [], id, node.id, here);
    if (found) return found;
  }
  return undefined;
}

export function moveUp(tree: Node[], id: string): Move | undefined {
  const at = locate(tree, id);
  if (!at || at.index === 0) return undefined;
  return { parent_id: at.parentId, position: at.index - 1 };
}

export function moveDown(tree: Node[], id: string): Move | undefined {
  const at = locate(tree, id);
  if (!at || at.index === at.siblings.length - 1) return undefined;
  // Positions are computed after removing the node, so "one further down"
  // is index + 1 in the list without it.
  return { parent_id: at.parentId, position: at.index + 1 };
}

/** Make the node the last child of its previous sibling. */
export function indent(tree: Node[], id: string): Move | undefined {
  const at = locate(tree, id);
  if (!at || at.index === 0) return undefined;
  const newParent = at.siblings[at.index - 1]!;
  return { parent_id: newParent.id, position: newParent.children?.length ?? 0 };
}

/** Move the node out of its parent, to just after that parent. */
export function outdent(tree: Node[], id: string): Move | undefined {
  const at = locate(tree, id);
  if (!at || at.parentId === null || !at.grandparent) return undefined;
  return { parent_id: at.grandparent.parentId, position: at.grandparent.index + 1 };
}
