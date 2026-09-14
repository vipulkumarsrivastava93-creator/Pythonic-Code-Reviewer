def build(items):
    result = []
    for x in items:
        result.append(x)
    return result


def visit(xs):
    for i in range(len(xs)):
        print(xs[i])


def check(value):
    if value == None:
        raise ValueError("nope")


def tally(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            d[k].append(v)
        else:
            d[k] = [v]
    return d