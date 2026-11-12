"""Minimal S-expression reader/writer for KiCad files."""


class Sym(str):
    """Bare (unquoted) token."""
    __slots__ = ()


def parse(text):
    pos = 0
    n = len(text)
    stack = [[]]
    while pos < n:
        c = text[pos]
        if c in ' \t\r\n':
            pos += 1
        elif c == '(':
            new = []
            stack[-1].append(new)
            stack.append(new)
            pos += 1
        elif c == ')':
            stack.pop()
            pos += 1
        elif c == '"':
            pos += 1
            buf = []
            while text[pos] != '"':
                if text[pos] == '\\':
                    pos += 1
                    ch = text[pos]
                    buf.append({'n': '\n', 't': '\t', 'r': '\r'}.get(ch, ch))
                else:
                    buf.append(text[pos])
                pos += 1
            pos += 1
            stack[-1].append(''.join(buf))
        else:
            start = pos
            while pos < n and text[pos] not in ' \t\r\n()':
                pos += 1
            stack[-1].append(Sym(text[start:pos]))
    return stack[0][0]


def quote(s):
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n') + '"'


def fmt_num(v):
    if isinstance(v, int):
        return str(v)
    s = ('%.4f' % v).rstrip('0').rstrip('.')
    return '0' if s in ('-0', '') else s


def dump(node, indent=0):
    """Serialise with one child list per line (compact leaves)."""
    pad = '\t' * indent
    if not isinstance(node, list):
        if isinstance(node, Sym):
            return str(node)
        if isinstance(node, str):
            return quote(node)
        return fmt_num(node)
    if all(not isinstance(c, list) for c in node):
        return '(' + ' '.join(dump(c) for c in node) + ')'
    head = []
    rest = []
    seen_list = False
    for c in node:
        if isinstance(c, list):
            seen_list = True
            rest.append(c)
        elif not seen_list:
            head.append(c)
        else:
            rest.append(c)
    out = '(' + ' '.join(dump(c) for c in head)
    for c in rest:
        out += '\n' + pad + '\t' + dump(c, indent + 1)
    out += '\n' + pad + ')'
    return out


def find(node, name):
    for c in node[1:]:
        if isinstance(c, list) and c and c[0] == name:
            return c
    return None


def find_all(node, name):
    return [c for c in node[1:] if isinstance(c, list) and c and c[0] == name]
