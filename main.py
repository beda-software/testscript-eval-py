from funcy.types import is_list, is_mapping


def walk_dict(d):
    for k, v in d.items():
        if is_list(v):
            d[k] = [walk_dict(vi) for vi in v]
        elif is_mapping(v) and "_value" not in v:
            d[k] = walk_dict(v)
        elif is_mapping(v) and "_value" in v:
            d[k] = v["_value"]
    return d
