#!/bin/bash
cmd=$(grep -e "core id" -e ^physical -e ^processor /proc/cpuinfo)
NUM_NUMA=$(lscpu | grep "NUMA node(s):" | cut -d ":" -f2 | xargs -n 2)
num_cpus=0
cpu_string=$1
mode=$2

#expand the cpu string in the form of "a-b,c-d" i.e ranges with - and comma separated string.
#eg: "1-4,9-10"
expand_string() {
    local IFS=','
    set -- $1
    for range; do
        case $range in
            *-*) for (( i=${range%-*}; i<=${range#*-}; i++ )); do echo $i; done ;;
            *)   echo "$range" ;;
        esac
    done
}

#find and return numa id of the cpu
get_numa() {
    echo ${cmd} | xargs -n 11 | grep "processor : $1 " | cut -d ":" -f 3 | \
              cut -d " " -f2
}

#find and return the phy core of the cpu
get_core() {
    echo ${cmd} | xargs -n 11 | grep "processor : $1 " | cut -d ":" -f 4 | \
              cut -d " " -f2
}

#find the sibling of the cpu
get_sibling() {
    echo ${cmd} | xargs -n 11 | grep "physical id : $2 core id : $3$" | \
                grep -v "processor : $1 " | cut -d ":" -f2 | cut -d " " -f2
}

#given a cpu find if the cpu is present in the pmd_list generated in this script
find_cpu_in_pmd_list() {
    local val=$1
    for elem in "${cpu_pmd[@]}"
    do
        if [ $elem -eq $val ]; then
            echo 1
            return
        fi
    done
    echo 0
}

cpus=( $(expand_string $cpu_string) )
num_cpus=${#cpus[@]}

#select the mode. In case no mode is there, fall bac to legacy custom
if [ -z "$2" ]; then
    mode="custom"
fi
if [ $mode == "ultra-perf" ] && [ $num_cpus -eq $(($NUM_NUMA * 4)) ]; then
    mode="ultra-perf"
elif [ $mode == "high-perf" ] && [ $num_cpus -eq $(($NUM_NUMA * 4))  ]; then
    mode="high-perf"
elif [ $mode == "normal-perf" ] && [ $num_cpus -eq $(($NUM_NUMA * 2)) ]; then
    mode="normal-perf"
else
    mode="custom"
fi

#for each cpu in cpu list check which list it needs to be added to 
for cpu in "${cpus[@]}"
do
    numa=($(get_numa $cpu))
    core=($(get_core $cpu))
    sibling=($(get_sibling $cpu $numa $core))
    if [ -z $sibling ] || [ $cpu -lt $sibling ]; then
        cpu_pmd+=($cpu)
    else
        case $mode in
            "normal-perf")
                cpu_pmd_ht+=($cpu)
                phy_pmd+=($cpu)
                ;;
            "custom")
                cpu_pmd_ht+=($cpu)
                ;;
            "ultra-perf")
                found=$(find_cpu_in_pmd_list $sibling)
                if [ $found -eq 1 ] && [ ${#phy_pmd[@]} -lt $(($NUM_NUMA * 2)) ] &&
                     ( [ -z $numa_used ] || [ $numa_used -ne $numa ] ); then
                    phy_pmd+=($sibling)
                    phy_pmd+=($cpu)
                    cpu_pmd_ht+=($cpu)
                    numa_used=$numa
                fi
                ;;
            "high-perf")
                found=$(find_cpu_in_pmd_list $sibling)
                if [ $found -eq 1 ] && [ ${#phy_pmd[@]} -lt $(($NUM_NUMA)) ] &&
                     ( [ -z $numa_used ] || [ $numa_used -ne $numa ] ); then
                    phy_pmd+=($sibling)
                    numa_used=$numa
                fi
                ;;
        esac
    fi
done
IFS=','

#create reference to external facts
mkdir -p /etc/facter/facts.d
echo "cpu_pmd_list: \"${cpu_pmd[*]}\"" > /etc/facter/facts.d/cpu_list.yaml
echo "cpu_pmd_ht_list: \"${cpu_pmd_ht[*]}\"" >> /etc/facter/facts.d/cpu_list.yaml
if [ $mode != "custom" ]; then
    echo "ovs_phy_pmd: \"${phy_pmd[*]}\"" >> /etc/facter/facts.d/cpu_list.yaml
    echo "ovs_phy_rxq: ${#phy_pmd[@]}" >> /etc/facter/facts.d/cpu_list.yaml
fi
