import ast

from vouch.mutants import collect_sites, make_mutant

SRC = """\
def f(a, b):
    if a > 10 and b == 2:
        return a + b
    return a - 1
"""


def test_collects_only_changed_lines():
    sites = collect_sites(SRC, {2})
    descriptions = [s.description for s in sites]
    assert any(">" in d for d in descriptions)
    assert any("==" in d for d in descriptions)
    assert any("and" in d for d in descriptions)
    assert all(s.line == 2 for s in sites)


def test_no_sites_outside_changed_lines():
    assert collect_sites(SRC, {99}) == []


def test_mutant_application_is_deterministic():
    sites = collect_sites(SRC, {2, 3, 4})
    for spec in sites:
        mutated = make_mutant(SRC, {2, 3, 4}, spec.index)
        assert mutated != ast.unparse(ast.parse(SRC)), spec.description
        ast.parse(mutated)  # every mutant must remain valid Python


def test_each_mutant_differs_in_one_site():
    sites = collect_sites(SRC, {2, 3, 4})
    mutants = {make_mutant(SRC, {2, 3, 4}, s.index) for s in sites}
    assert len(mutants) == len(sites)
