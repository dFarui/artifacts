#!/bin/bash
set -x
virsh list >& /dev/null || exit 0

for vm in $(virsh list --all --name |grep -vE '^$')
do
   virsh domiflist $vm |tail -n +3 |grep -w bridge| \
   while read -r iface type bridge _
   do
       [ $type = 'bridge' ] && ip link set $iface master $bridge
   done
done
