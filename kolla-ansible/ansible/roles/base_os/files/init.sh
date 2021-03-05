#!/bin/bash

installroot=$1
user=$2
password=$3
if [ -z $installroot ]; then
    echo "installroot is not specified"
    exit 1
fi
if [ ! -d $installroot ]; then
    echo "$installroot is not an existing direcory"
    exit 1
fi
cp -a /home $installroot
cp -a /etc/{sudoers,ansible,hosts} $installroot/etc
mkdir -p $installroot/etc/sysconfig
cp -a /etc/sysconfig/network $installroot/etc/sysconfig
cat << EOF | chroot $installroot
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t devtmpfs devtmpfs /dev
mkdir -p /dev/pts
mount -t devpts devpts /dev/pts
[ -d /sys/firmware/efi ] && mount -t efivarfs efivarfs /sys/firmware/efi/efivars
cp /etc/mtab /etc/fstab
sshd-gen-keys-start &>/dev/null
groupadd sudo
useradd  -U -G sudo $user
echo -e "$password\n$password" | passwd $user
ln -s /usr/lib/systemd/system/sshd.service /etc/systemd/system/multi-user.target.wants/sshd.service
/sbin/mkinitrd
/usr/sbin/grub2-mkconfig -o /boot/grub2/grub.cfg
[ -d /sys/firmware/efi ] && /usr/sbin/shim-install --config-file\=/boot/grub2/grub.cfg
EOF
#pkill -9 sshd && /usr/sbin/sshd -D &
#/usr/sbin/shim-install --config-file\=/boot/grub2/grub.cfg
rm /install_in_progress
