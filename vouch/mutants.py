"""AST-based mutant generation, scoped to a set of changed lines."""
from __future__ import annotations

import ast
from dataclasses import dataclass

_CMP_SWAP = {
    ast.Gt: ast.GtE, ast.GtE: ast.Gt,
    ast.Lt: ast.LtE, ast.LtE: ast.Lt,
    ast.Eq: ast.NotEq, ast.NotEq: ast.Eq,
    ast.Is: ast.IsNot, ast.IsNot: ast.Is,
    ast.In: ast.NotIn, ast.NotIn: ast.In,
}
_BIN_SWAP = {
    ast.Add: ast.Sub, ast.Sub: ast.Add,
    ast.Mult: ast.Div, ast.Div: ast.Mult,
    ast.FloorDiv: ast.Div, ast.Mod: ast.Mult,
}
_OP_SYMBOL = {
    ast.Gt: ">", ast.GtE: ">=", ast.Lt: "<", ast.LtE: "<=",
    ast.Eq: "==", ast.NotEq: "!=", ast.Is: "is", ast.IsNot: "is not",
    ast.In: "in", ast.NotIn: "not in",
    ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/",
    ast.FloorDiv: "//", ast.Mod: "%", ast.And: "and", ast.Or: "or",
}


@dataclass
class MutantSpec:
    index: int
    line: int
    description: str


class _Walker(ast.NodeTransformer):
    """Single pass that both enumerates mutation sites and (when `apply_index`
    is set) applies exactly one mutation. Deterministic traversal order keeps
    enumeration and application in sync across parses of the same source."""

    def __init__(self, changed_lines: set[int], apply_index: int | None = None):
        self.changed_lines = changed_lines
        self.apply_index = apply_index
        self.counter = -1
        self.sites: list[MutantSpec] = []

    def _site(self, node: ast.AST, description: str) -> bool:
        if getattr(node, "lineno", None) not in self.changed_lines:
            return False
        self.counter += 1
        self.sites.append(MutantSpec(self.counter, node.lineno, description))
        return self.apply_index == self.counter

    def visit_Compare(self, node: ast.Compare):
        self.generic_visit(node)
        op = type(node.ops[0])
        if op in _CMP_SWAP:
            new = _CMP_SWAP[op]
            if self._site(node, f"`{_OP_SYMBOL[op]}` → `{_OP_SYMBOL[new]}`"):
                node.ops[0] = new()
        return node

    def visit_BinOp(self, node: ast.BinOp):
        self.generic_visit(node)
        op = type(node.op)
        if op in _BIN_SWAP:
            new = _BIN_SWAP[op]
            if self._site(node, f"`{_OP_SYMBOL[op]}` → `{_OP_SYMBOL[new]}`"):
                node.op = new()
        return node

    def visit_BoolOp(self, node: ast.BoolOp):
        self.generic_visit(node)
        op = type(node.op)
        new = ast.Or if op is ast.And else ast.And
        if self._site(node, f"`{_OP_SYMBOL[op]}` → `{_OP_SYMBOL[new]}`"):
            node.op = new()
        return node

    def visit_UnaryOp(self, node: ast.UnaryOp):
        self.generic_visit(node)
        if isinstance(node.op, ast.Not):
            if self._site(node, "remove `not`"):
                return node.operand
        return node

    def visit_Constant(self, node: ast.Constant):
        if isinstance(node.value, bool):
            if self._site(node, f"`{node.value}` → `{not node.value}`"):
                return ast.copy_location(ast.Constant(value=not node.value), node)
        elif isinstance(node.value, int):
            if self._site(node, f"`{node.value}` → `{node.value + 1}`"):
                return ast.copy_location(ast.Constant(value=node.value + 1), node)
        return node


def collect_sites(source: str, changed_lines: set[int]) -> list[MutantSpec]:
    walker = _Walker(changed_lines, apply_index=None)
    walker.visit(ast.parse(source))
    return walker.sites


def make_mutant(source: str, changed_lines: set[int], index: int) -> str:
    walker = _Walker(changed_lines, apply_index=index)
    tree = walker.visit(ast.parse(source))
    ast.fix_missing_locations(tree)
    return ast.unparse(tree)
