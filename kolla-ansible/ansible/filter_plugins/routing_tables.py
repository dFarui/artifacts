#
# Generate routing table from interface dicts
#


def routing_tables(ifdictlistlist):
    ''' Recover all routing_tables in a nested list of
        interface specifications
    '''
    output = []
    for ifdictlist in ifdictlistlist:
        for ifdict in ifdictlist:
            if 'routing_table' in ifdict:
                output.append(ifdict['routing_table'])

    return output


class FilterModule(object):
    def filters(self):
        return {'routing_tables': routing_tables}
