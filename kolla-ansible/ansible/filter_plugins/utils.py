import yaml


def filter_list(l, key, value, key2):
    return [x[key2] for x in l if x[key] == value]


class FilterModule(object):
    def filters(self):
        return {
            'dictattr': filter_list,
        }
