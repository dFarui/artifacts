class FilterModule(object):

    def filters(self):
        return {
            'append_host_mounts': self.append_host_mounts,
        }

    def append_host_mounts(self, default_volumes, extra_volumes):
        volume_list = default_volumes
        for volume in extra_volumes:
            volume_list.append("{0}:/hostmount/{0}:ro".format(volume['mount']))
        return volume_list
