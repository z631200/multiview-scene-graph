# pddl_goal.py
"""A minimal PDDL goal parser + evaluator (goal formula only).

Supported subset (enough to mimic ALFRED-style goals):
- (and ...)
- (not X)
- (exists (<typed-vars>) X)
- (forall (<typed-vars>) X)
- Predicates:
  - (opened ?r)                  -> THOR obj['isOpen'] == True
  - (inReceptacle ?o ?r)         -> ?r.objectId in ?o.parentReceptacles (substring match fallback)
  - (objectType ?o AppleType)    -> ?o.objectType == 'Apple' (accepts 'AppleType' or 'Apple')
  - (receptacleType ?r BowlType) -> ?r.objectType == 'Bowl' (accepts 'BowlType' or 'Bowl')
- Generic property predicate fallback:
  - (isCooked ?o True) / (isCooked ?o) etc. -> compare to metadata fields on the bound object
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple, Union

###############################################################################
# AST nodes
###############################################################################

@dataclass(frozen=True)
class Expr:
    pass

@dataclass(frozen=True)
class And(Expr):
    items: Tuple[Expr, ...]

@dataclass(frozen=True)
class Not(Expr):
    item: Expr

@dataclass(frozen=True)
class Exists(Expr):
    typed_vars: Tuple[Tuple[str, str], ...]  # (var, type)
    body: Expr

@dataclass(frozen=True)
class ForAll(Expr):
    typed_vars: Tuple[Tuple[str, str], ...]
    body: Expr

@dataclass(frozen=True)
class Pred(Expr):
    name: str
    args: Tuple[str, ...]

###############################################################################
# Parser
###############################################################################

def _tokenize(s: str) -> List[str]:
    # Remove comments starting with ';;'
    lines = []
    for ln in s.splitlines():
        if ';;' in ln:
            ln = ln.split(';;', 1)[0]
        lines.append(ln)
    s = '\n'.join(lines)

    tokens: List[str] = []
    buf = ''
    for ch in s:
        if ch in ('(', ')'):
            if buf.strip():
                tokens.append(buf.strip())
            tokens.append(ch)
            buf = ''
        elif ch.isspace():
            if buf.strip():
                tokens.append(buf.strip())
                buf = ''
        else:
            buf += ch
    if buf.strip():
        tokens.append(buf.strip())
    return tokens

def _parse_sexp(tokens: List[str]) -> Any:
    if not tokens:
        raise ValueError('Empty token stream')
    tok = tokens.pop(0)
    if tok == '(':
        lst = []
        while tokens and tokens[0] != ')':
            lst.append(_parse_sexp(tokens))
        if not tokens:
            raise ValueError("Unclosed '(' in PDDL")
        tokens.pop(0)
        return lst
    if tok == ')':
        raise ValueError("Unexpected ')'")
    return tok

def parse_goal_pddl(pddl: str) -> Expr:
    tokens = _tokenize(pddl)
    sexp = _parse_sexp(tokens)
    if tokens:
        raise ValueError(f'Trailing tokens after parsing PDDL: {tokens[:10]}')

    goal_expr = sexp
    if isinstance(sexp, list) and sexp:
        if sexp[0] == ':goal':
            if len(sexp) != 2:
                raise ValueError('(:goal ...) must contain exactly one expression')
            goal_expr = sexp[1]
        elif _contains_goal_clause(sexp):
            goal_expr = _extract_goal_clause(sexp)

    return _sexp_to_ast(goal_expr)

def _contains_goal_clause(sexp: Any) -> bool:
    if isinstance(sexp, list):
        if sexp and sexp[0] == ':goal':
            return True
        return any(_contains_goal_clause(x) for x in sexp)
    return False

def _extract_goal_clause(sexp: Any) -> Any:
    if isinstance(sexp, list):
        if sexp and sexp[0] == ':goal':
            if len(sexp) != 2:
                raise ValueError('(:goal ...) must contain exactly one expression')
            return sexp[1]
        for x in sexp:
            if _contains_goal_clause(x):
                return _extract_goal_clause(x)
    raise ValueError('No :goal clause found')

def _parse_typed_vars(lst: Any) -> Tuple[Tuple[str, str], ...]:
    if not isinstance(lst, list):
        raise ValueError('Typed var list must be a list')
    items = lst[:]
    out: List[Tuple[str, str]] = []
    i = 0
    while i < len(items):
        var = items[i]
        if not isinstance(var, str) or not var.startswith('?'):
            raise ValueError(f"Expected variable like '?x', got: {var}")
        if i + 2 >= len(items) or items[i + 1] != '#':
            raise ValueError("Expected ALFRED-style typed vars: (?x # type)")
        typ = items[i + 2]
        if not isinstance(typ, str):
            raise ValueError(f'Expected type name, got: {typ}')
        out.append((var, typ))
        i += 3
    return tuple(out)

def _sexp_to_ast(sexp: Any) -> Expr:
    if isinstance(sexp, str):
        raise ValueError(f'Unexpected atom as expression: {sexp}')
    if not isinstance(sexp, list) or not sexp:
        raise ValueError(f'Invalid expression: {sexp}')

    head = sexp[0]
    if head == 'and':
        return And(tuple(_sexp_to_ast(x) for x in sexp[1:]))
    if head == 'not':
        if len(sexp) != 2:
            raise ValueError('(not ...) must have exactly one child')
        return Not(_sexp_to_ast(sexp[1]))
    if head == 'exists':
        if len(sexp) != 3:
            raise ValueError('(exists (<typed-vars>) <body>) expected')
        typed_vars = _parse_typed_vars(sexp[1])
        return Exists(typed_vars, _sexp_to_ast(sexp[2]))
    if head == 'forall':
        if len(sexp) != 3:
            raise ValueError('(forall (<typed-vars>) <body>) expected')
        typed_vars = _parse_typed_vars(sexp[1])
        return ForAll(typed_vars, _sexp_to_ast(sexp[2]))

    name = str(head)
    args = tuple(str(a) for a in sexp[1:])
    return Pred(name=name, args=args)

###############################################################################
# Evaluator
###############################################################################

class GoalEvaluator:
    def __init__(self, objects: List[Dict[str, Any]]):
        self.objects = objects
        self.by_id = {o.get('objectId'): o for o in objects if isinstance(o.get('objectId'), str)}

    def eval(self, expr: Expr) -> Tuple[bool, Dict[str, Any]]:
        env: Dict[str, Dict[str, Any]] = {}
        ok = self._eval(expr, env)
        return ok, {'goal_ok': ok}

    def _domain(self, typ: str) -> List[Dict[str, Any]]:
        t = typ.lower()
        if t == 'object':
            return self.objects
        if t == 'receptacle':
            return [o for o in self.objects if o.get('receptacle') is True or o.get('openable') is True]
        return self.objects

    def _eval(self, expr: Expr, env: Dict[str, Dict[str, Any]]) -> bool:
        if isinstance(expr, And):
            return all(self._eval(x, env) for x in expr.items)
        if isinstance(expr, Not):
            return not self._eval(expr.item, env)
        if isinstance(expr, Exists):
            return self._eval_quantifier(expr.typed_vars, expr.body, env, is_forall=False)
        if isinstance(expr, ForAll):
            return self._eval_quantifier(expr.typed_vars, expr.body, env, is_forall=True)
        if isinstance(expr, Pred):
            return self._eval_pred(expr, env)
        raise TypeError(f'Unknown Expr type: {type(expr)}')

    def _eval_quantifier(
        self,
        typed_vars: Tuple[Tuple[str, str], ...],
        body: Expr,
        env: Dict[str, Dict[str, Any]],
        is_forall: bool,
    ) -> bool:
        def rec(i: int) -> bool:
            if i >= len(typed_vars):
                return self._eval(body, env)

            var, typ = typed_vars[i]
            domain = self._domain(typ)

            if is_forall:
                for obj in domain:
                    env[var] = obj
                    if not rec(i + 1):
                        env.pop(var, None)
                        return False
                env.pop(var, None)
                return True
            else:
                for obj in domain:
                    env[var] = obj
                    if rec(i + 1):
                        env.pop(var, None)
                        return True
                env.pop(var, None)
                return False

        return rec(0)

    def _resolve_arg(self, a: str, env: Dict[str, Dict[str, Any]]) -> Union[Dict[str, Any], str]:
        if a.startswith('?'):
            if a not in env:
                raise ValueError(f'Unbound variable in goal: {a}')
            return env[a]
        return a

    @staticmethod
    def _strip_type_suffix(s: str) -> str:
        return s[:-4] if s.endswith('Type') else s

    def _eval_pred(self, pred: Pred, env: Dict[str, Dict[str, Any]]) -> bool:
        name = pred.name

        if name == 'opened':
            if len(pred.args) != 1:
                raise ValueError('(opened ?r) expects 1 arg')
            r = self._resolve_arg(pred.args[0], env)
            return isinstance(r, dict) and (r.get('isOpen') is True)

        if name == 'inReceptacle':
            if len(pred.args) != 2:
                raise ValueError('(inReceptacle ?o ?r) expects 2 args')
            o = self._resolve_arg(pred.args[0], env)
            r = self._resolve_arg(pred.args[1], env)
            if not isinstance(o, dict) or not isinstance(r, dict):
                return False
            r_id = r.get('objectId')
            parents = o.get('parentReceptacles')
            if not isinstance(r_id, str):
                return False
            if isinstance(parents, list):
                return any(isinstance(pid, str) and (pid == r_id or r_id in pid) for pid in parents)
            if isinstance(parents, str):
                return parents == r_id or (r_id in parents)
            return False

        if name == 'objectType':
            if len(pred.args) != 2:
                raise ValueError('(objectType ?o XType) expects 2 args')
            o = self._resolve_arg(pred.args[0], env)
            typ = self._resolve_arg(pred.args[1], env)
            if not isinstance(o, dict) or not isinstance(typ, str):
                return False
            t = self._strip_type_suffix(typ)
            return o.get('objectType') == t

        if name == 'receptacleType':
            if len(pred.args) != 2:
                raise ValueError('(receptacleType ?r XType) expects 2 args')
            r = self._resolve_arg(pred.args[0], env)
            typ = self._resolve_arg(pred.args[1], env)
            if not isinstance(r, dict) or not isinstance(typ, str):
                return False
            t = self._strip_type_suffix(typ)
            return r.get('objectType') == t

        # Generic property predicate fallback:
        #   (isCooked ?o True) / (isCooked ?o) / (parentReceptacles ?o Bowl)
        if len(pred.args) >= 1:
            ent = self._resolve_arg(pred.args[0], env)
            if not isinstance(ent, dict):
                return False

            if len(pred.args) == 1:
                return ent.get(name) is True

            expected = _parse_literal(pred.args[1])
            actual = ent.get(name)

            if name == 'parentReceptacles':
                if isinstance(actual, list):
                    return any(isinstance(x, str) and str(expected) in x for x in actual)
                if isinstance(actual, str):
                    return str(expected) in actual
                return False

            return actual == expected

        raise ValueError(f'Invalid predicate: {pred}')

def _parse_literal(s: str) -> Any:
    if s in ('True', 'true'):
        return True
    if s in ('False', 'false'):
        return False
    try:
        if '.' in s:
            return float(s)
        return int(s)
    except Exception:
        return s
