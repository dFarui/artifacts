# This plugin provides the following filters.
# pci_hw_address: Get the pci bus address of the pci card using
#                 the device name by searching a mapping table.
#

from ansible import errors


def pci_hw_address(devname, mapping_table):
    if not devname:
        raise errors.AnsibleFilterError("ERROR: null or empty device name")

    hw_address = ''
    for mapping in mapping_table:
        if mapping.get('name', '') == devname:
            hw_address = mapping.get('busAddress', '')
            break

    if not hw_address:
        raise errors.AnsibleFilterError("ERROR: PCI H/W address "
                                        "not found for " + devname)

    return hw_address


class FilterModule(object):

    def filters(self):
        return {
                'pci_hw_address': pci_hw_address,
               }
