class FilterModule(object):
    def filters(self):
        return {
            'get_partitions': get_partitions,
        }


KiB = 1024
MiB = KiB*1024
GiB = MiB*1024

guard_size_mib = 1
mbr_size_mib = 6
boot_size_mib = 350
efi_size_mib = 200


def get_partitions(configured_disks, found_disks, devlinks={}, bootmode=""):
    '''
    :retuns: the partitions to be created
    :param:  configured_disks: my_disk_assignments
    :param:  found_disks:      ansible_devices
    :param:  devlinks:         ansible_local.disk_devlinks
    :param:  bootmode:         ansible_local.bootmode
    '''
    def get_size_mib(size, hundredpercent_mib=None):
        if size[-3:] == 'KiB':
            return int(size[:-3]) / 1024
        elif size[-3:] == 'MiB':
            return int(size[:-3])
        elif size[-3:] == 'GiB':
            return int(size[:-3]) * 1024
        elif size[-1:] == '%':
            return int(int(size[:-1]) * hundredpercent_mib / 100)
        else:
            raise Exception(f"Invalid partition size {size}")

    def size_partitions(disk):
        if 'partitions' not in disk:
            return
        allocated_mib = 0
        part_with_max = None
        for part in disk['partitions']:
            if part['size'] == 'max':
                if part_with_max:
                    raise Exception(f"Multiple partitions with max "
                                    f"allocation in disk {disk['name']}")
                part_with_max = part
                continue
            size_mib = get_size_mib(part['size'], disk['usable_mib'])
            part['size_mib'] = size_mib
            allocated_mib += size_mib
            if allocated_mib > disk['full_size_mib']:
                raise Exception(f"Not enough space in disk {disk['name']} "
                                f"for part {part['name']}")
        if part_with_max:
            size_mib = disk['full_size_mib'] - allocated_mib
            part_with_max['size_mib'] = size_mib

        next_free_mib = guard_size_mib
        part_number = 1
        for part in disk['partitions']:
            part_name_map[part['name']] = \
                f'/dev/disk/by-partlabel/{part["name"]}'
            part['number'] = part_number
            part_number += 1
            part['part_start'] = f'{next_free_mib}MiB'
            next_free_mib += part['size_mib']
            part['part_end'] = f'{next_free_mib}MiB'
            part['device'] = disk['devpath']
            part['label'] = disk['labelType']
            partition_list.append(part)

    configured_disks['partition_list'] = []
    configured_disks['lv_list'] = []
    configured_disks['bootable_disks'] = []

    partition_list = configured_disks['partition_list']
    lv_list = configured_disks['lv_list']
    bootable_disks = configured_disks['bootable_disks']

    part_name_map = {}
    found_disk_devpaths = [f'/dev/{k}' for k in found_disks.keys()]
# These commented lines are left here intentionally to preserve how to
# use pdb for debugging
#    import sys
#    sys.stdin = open('/dev/tty')
#    import pdb
#    pdb.set_trace()
    bootable_disk_found = False
    for disk in configured_disks['drives']:

        if not disk['type'] in ['local', 'virtual']:
            # skipping non local disks for now
            continue

        device = None
        if disk['id'] in found_disk_devpaths:
            devpath = disk['id']
        elif disk['id'] in devlinks:
            devpath = devlinks[disk['id']]
        else:
            raise Exception(f"Configured disk id {disk['id']} is not found")
        device = found_disks[devpath.split('/')[-1]]
        disk['devpath'] = devpath

        full_size_mib = (
            int((int(device['sectors']) * int(device['sectorsize'])) / MiB -
                2 * guard_size_mib))
        disk['full_size_mib'] = full_size_mib
        disk['usable_mib'] = disk['full_size_mib']

        # TODO
        # checking bootable flag and adding mandatory partitions may go
        # to generator
        parts = disk.get('partitions')
        if disk['bootable']:
            if bootable_disk_found:
                raise Exception("Multiple bootable disks are defined. "
                                "Currently only one is allowed")
            bootable_disks.append(disk['devpath'])
            bootable_disk_found = True
            disk['usable_mib'] = (disk['full_size_mib'] -
                                  mbr_size_mib - boot_size_mib - efi_size_mib)
            # NB Order is important, the mbr and efi must be first for the
            #    Ansible parted module to function properly. If the order is
            #    changed then manual parted/gdisk commands have to be used to
            #     set the flags.
            parts.insert(0, {'name': 'mbr', 'size': f'{mbr_size_mib}MiB'})
            parts.insert(1, {'name': 'efi', 'size': f'{efi_size_mib}MiB'})
            parts.insert(2, {'name': 'boot', 'size': f'{boot_size_mib}MiB'})
            configured_disks['volumes'].append({
                "format": True,
                "fstype": "ext4",
                "mount": "/boot",
                "name": "boot",
                "type": "partition",
                "partname": "boot"
            })
            configured_disks['volumes'].append({
                "format": True,
                "fstype": "vfat",
                "mount": "/boot/efi",
                "name": "efi",
                "type": "partition",
                "partname": "efi"
            })
        elif parts:
            disk['usable_mib'] = disk['full_size_mib'] - mbr_size_mib
            parts.insert(0, {'name': 'mbr', 'size': f'{mbr_size_mib}MiB'})

        size_partitions(disk)
    configured_disks['part_name_map'] = part_name_map
    for vg in configured_disks['volumeGroups']:
        pvlist = []
        for pv in vg['physicalVolumes']:
            if pv['type'] == 'partition':
                pname = pv['partname']
                pv['device'] = part_name_map[pname]
                pvlist.append(pv['device'])
            else:
                raise Exception(
                    f"Type {pv['type']} is not a supported pv type")
        vg['pvs'] = ','.join(pvlist)

        for lv in vg['logicalVolumes']:
            if lv['size'][-1:] == '%':
                lv['size'] = f'{lv["size"]}VG'
            if lv['size'][-2:] == 'iB':
                lv['size'] = lv['size'][:-2]
            lv['vg'] = vg['name']
            lv_list.append(lv)

    # sorting the volumes by the mount path.
    # the magic with the replace/split.join is to replace potential multiple
    # slashes with single one this may be done nicer with regex
    volumes = configured_disks['volumes']
    # volumes = sorted(
    #     volumes,
    #     key=lambda vol:
    #     len(vol.get('mount', '').replace('/', ' ').split()))
    volumes = sorted(
        volumes,
        key=lambda vol:
        '/'.join(vol.get('mount', '').replace('/', ' ').split()))
    for vol in volumes:
        if vol['type'] == 'lvm':
            vol['device'] = f'/dev/{vol["volumeGroup"]}/{vol["logicalVolume"]}'
        if vol['type'] == 'partition':
            vol['device'] = part_name_map[vol['partname']]

    configured_disks['volumes'] = volumes

    return configured_disks
