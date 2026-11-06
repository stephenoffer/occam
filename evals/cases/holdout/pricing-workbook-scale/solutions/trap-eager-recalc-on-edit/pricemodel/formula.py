"""Parser and evaluator for the formula language.

parse() turns formula text into a tree of tuples:
    ("num", value)  ("ref", name)  ("neg", node)  ("op", symbol, left, right)  ("call", name, args)
"""

import operator
import re

TOKEN = re.compile(
    r"\s*(?:(?P<num>\d+\.?\d*|\.\d+)|(?P<name>[A-Za-z_][A-Za-z0-9_.]*)|(?P<sym><=|>=|<>|[-+*/(),<>=]))"
)

FUNCTIONS = {
    "SUM": lambda *values: sum(values),
    "MIN": min,
    "MAX": max,
    "ABS": abs,
    "ROUND": lambda value, digits=0: round(value, int(digits)),
}

ARITHMETIC = {"+": operator.add, "-": operator.sub, "*": operator.mul, "/": operator.truediv}
COMPARISON = {"=": operator.eq, "<>": operator.ne, "<": operator.lt, "<=": operator.le,
              ">": operator.gt, ">=": operator.ge}


class FormulaError(ValueError):
    """The formula text could not be parsed."""


def tokenize(text):
    tokens, position = [], 0
    text = text.rstrip()
    while position < len(text):
        match = TOKEN.match(text, position)
        if match is None:
            raise FormulaError(f"unexpected character at {position} in {text!r}")
        tokens.append((match.lastgroup, match.group(match.lastgroup)))
        position = match.end()
    return tokens


class Parser:
    def __init__(self, text):
        self.text = text
        self.tokens = tokenize(text)
        self.position = 0

    def peek(self):
        return self.tokens[self.position][1] if self.position < len(self.tokens) else None

    def take(self):
        if self.position >= len(self.tokens):
            raise FormulaError(f"unexpected end of {self.text!r}")
        token = self.tokens[self.position]
        self.position += 1
        return token

    def expect(self, symbol):
        if self.take()[1] != symbol:
            raise FormulaError(f"expected {symbol!r} in {self.text!r}")

    def parse(self):
        node = self.comparison()
        if self.position != len(self.tokens):
            raise FormulaError(f"unexpected {self.peek()!r} in {self.text!r}")
        return node

    def comparison(self):
        node = self.additive()
        while self.peek() in COMPARISON:
            symbol = self.take()[1]
            node = ("op", symbol, node, self.additive())
        return node

    def additive(self):
        node = self.term()
        while self.peek() in ("+", "-"):
            symbol = self.take()[1]
            node = ("op", symbol, node, self.term())
        return node

    def term(self):
        node = self.unary()
        while self.peek() in ("*", "/"):
            symbol = self.take()[1]
            node = ("op", symbol, node, self.unary())
        return node

    def unary(self):
        if self.peek() == "-":
            self.take()
            return ("neg", self.unary())
        return self.atom()

    def atom(self):
        kind, value = self.take()
        if kind == "num":
            return ("num", float(value))
        if kind == "name":
            if self.peek() == "(":
                return self.call(value)
            return ("ref", value)
        if value == "(":
            node = self.comparison()
            self.expect(")")
            return node
        raise FormulaError(f"unexpected {value!r} in {self.text!r}")

    def call(self, name):
        if name != "IF" and name not in FUNCTIONS:
            raise FormulaError(f"unknown function {name} in {self.text!r}")
        self.expect("(")
        args = []
        if self.peek() != ")":
            args.append(self.comparison())
            while self.peek() == ",":
                self.take()
                args.append(self.comparison())
        self.expect(")")
        if name == "IF" and len(args) != 3:
            raise FormulaError(f"IF takes three arguments in {self.text!r}")
        return ("call", name, args)


def parse(text):
    return Parser(text).parse()


def evaluate(node, lookup):
    """Compute a parsed formula, calling lookup(name) for each cell it reads."""
    kind = node[0]
    if kind == "num":
        return node[1]
    if kind == "ref":
        return lookup(node[1])
    if kind == "neg":
        return -evaluate(node[1], lookup)
    if kind == "op":
        left = evaluate(node[2], lookup)
        right = evaluate(node[3], lookup)
        if node[1] in ARITHMETIC:
            return ARITHMETIC[node[1]](left, right)
        return 1.0 if COMPARISON[node[1]](left, right) else 0.0
    if node[1] == "IF":
        test, then, otherwise = node[2]
        return evaluate(then if evaluate(test, lookup) else otherwise, lookup)
    return FUNCTIONS[node[1]](*[evaluate(arg, lookup) for arg in node[2]])


def references(node):
    """Return the names of all cells a parsed formula could read."""
    found, stack = set(), [node]
    while stack:
        current = stack.pop()
        kind = current[0]
        if kind == "ref":
            found.add(current[1])
        elif kind == "neg":
            stack.append(current[1])
        elif kind == "op":
            stack.extend(current[2:])
        elif kind == "call":
            stack.extend(current[2])
    return found
