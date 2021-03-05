# Filter plugin to provide hyper threaded siblings for a set of cpus
#
# Usage :
#       "cpu1,cpu2" | ht_siblings
#     => "cpuh1,cpuh2"
import sys


def get_core_id(core_details, cpu):
    for core in core_details:
        for field in ["processor", "core id", "physical id"]:
            if field not in core:
                print("Error getting '%s' value from /proc/cpuinfo" % field)
                sys.exit(1)
            core[field] = int(core[field])
        if core["processor"] == int(cpu):
            return core["core id"], core["physical id"]


def get_HT_sibling(core_details, core_id, socket_id, cpu):
    for core in core_details:
        for field in ["processor", "core id", "physical id"]:
            if field not in core:
                print("Error getting '%s' value from /proc/cpuinfo" % field)
                sys.exit(1)
            core[field] = int(core[field])
        if core["core id"] == core_id and core["physical id"] == socket_id:
            if core["processor"] != int(cpu):
                return core["processor"]


def ht_siblings(cpu_set):
    cpus = cpu_set.split(',')
    fd = open("/proc/cpuinfo")
    lines = fd.readlines()
    fd.close()
    core_details = []
    core_lines = {}
    for line in lines:
        if len(line.strip()) != 0:
            name, value = line.split(":", 1)
            core_lines[name.strip()] = value.strip()
        else:
            core_details.append(core_lines)
            core_lines = {}
    hts = []
    for cpu in cpus:
        core_id, socket_id = get_core_id(core_details, cpu)
        ht_cpu = get_HT_sibling(core_details, core_id, socket_id, cpu)
        hts.append(ht_cpu)
    return ','.join(str(e) for e in hts)


class FilterModule(object):
    def filters(self):
        return {'ht_siblings': ht_siblings}
