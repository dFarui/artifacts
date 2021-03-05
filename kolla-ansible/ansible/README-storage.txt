
   Storage guide for vxflexos/nexenta
   ==================================

   The storage can be vxflexos and/or nexenta.

   In case of nexenta, cee-next is only "client", so only a cinder config needed
   In case of vxflexos, client only or embedded modes can be used.


1. Set storage related configs:

    For VxflexOS, set a config like in DC150:

    In disk_assignment.yaml -- add scaleio volume group and sds_dev
    partition:

  - name: compute-disks
    drives:
      - name: disk1
        type: local
        id: /dev/sda
        labelType: gpt
        bootable: true
        partitions:
          - name: lvm_pv_1
            size: max
          - name: lvm_pv_2
            size: 150GiB
    volumeGroups:
      - name: scaleio
        physicalVolumes:
          - type: partition
            partname: lvm_pv_2
        logicalVolumes:
          - name: sds_dev
            size: 100%



    In software.yaml -- add scaleio to software config:

  - name: scaleio
    versions:
      - version: 3.0.1.1
        url: '/repos/scaleio'
    type: rpm-md
    priority: 80



    In softwareAllocation.yaml -- add software allocation:

  - name: hostOS-v1
    software:
      - name: hostos
        version: sles15sp2
      - name: cee-host-extras
        version: sles15sp2
      - name: scaleio
        version: 3.0.1.1



    In interface_assignment.yaml -- add scaleio network configuration

networkSchemes:
  - name: scaleio_frontend
    interfaceList:
      - name: sio_fe0
        type: vlan
        mtu: 1500
        provider: linux
        firewallZone: cee
        sourceInterface: storage0
        network: sio_fe_san_pda
      - name: sio_fe1
        type: vlan
        mtu: 1500
        provider: linux
        firewallZone: cee
        sourceInterface: storage1
        network: sio_fe_san_pdb
  - name: scaleio_backend
    interfaceList:
      - name: sio_be0
        type: vlan
        mtu: 1500
        provider: linux
        firewallZone: cee
        sourceInterface: storage0
        network: sio_be_san_pda
      - name: sio_be1
        type: vlan
        mtu: 1500
        provider: linux
        firewallZone: cee
        sourceInterface: storage1
        network: sio_be_san_pdb

interfaceAssignments:
  - name: controller_lcm
    networkScheme:
      - scaleio_frontend
      - scaleio_backend

  - name: compute
    networkScheme:
      - scaleio_frontend
      - scaleio_backend

  - name: compute_sriov
    networkScheme:
      - scaleio_frontend
      - scaleio_backend



Select and use cinder-volume.conf from template configs for your DC:

  config-files/templates/custom-openstack-ipv4/services/default/config/cinder/cinder-volume.conf
  config-files/templates/custom-openstack-ipv6/services/default/config/cinder/cinder-volume.conf
  config-files/templates/openstack-ipv4/services/default/config/cinder/cinder-volume.conf
  config-files/templates/openstack-ipv6/services/default/config/cinder/cinder-volume.conf



2. Import the vxflexos artifacts:

   cd /tmp

   In case of only you use only client VxSDS:
     wget  https://arm.sero.gic.ericsson.se/artifactory/proj-ecs-dev-local/egbotth/cee_next/scaleio/vxsds-client-CXC1743286_8-P1A01.tgz --no-check-certificate

   In othe cases get embedded VxSDS as well:
     wget  https://arm.sero.gic.ericsson.se/artifactory/proj-ecs-dev-local/egbotth/cee_next/scaleio/vxsds-embedded-CXC1740177_8-P1A01.tgz --no-check-certificate

   tar zxvf <yourartifact.tgz>

   ansible-playbook /opt/cee/source/ansible/cee-artifacts.yml -e type=iso -e artifact_uri="/tmp/<your.iso>" -e metadata_uri="/tmp<yourMetdata.yaml>" -e cee_action=import


3. Set the inventories based on templates:

   Take:

     lcm/ansible/inventory/cinder_backends_example.yml

     lcm/ansible/inventory/vxflexos.example.yml

   as examples and create your own inventories based on that.

   For using nexenta backend, set config like this in
   lcm/ansible/inventory/cinder_backends_example.yml:

        cinder_volume_backends:
          nexentanfs-1:
            volume_driver: cinder.volume.drivers.nexenta.ns5.nfs.NexentaNfsDriver
            nexenta_password: Nexenta@1
            nas_mount_options: vers=3,minorversion=0,timeo=100,nolock
            nas_host: 192.168.17.101
            nexenta_user: admin
            nexenta_rest_port: 8443
            nexenta_rest_connect_timeout: 10
            nexenta_rest_address: 192.168.17.101
            nas_share_path: ericsson/cinder

   For using vxflexos backend, set config like this in
   lcm/ansible/inventory/cinder_backends_example.yml:

        cinder_volume_backends:
          vxflexos:
            type: vxflexos
            san_thin_provision: true
            storage_pools: protection_domain1:pool1,protection_domain1:pool2,protection_domain2:pool1
            default_protection_domain_name: protection_domain1
            default_storage_pool_name: pool1
            max_over_subscription_ratio: 10
            round_volume_capacity: true
            unmap_volume_before_deletion: true
            verify_server_certificate: False
            server_certificate_path: None
            allow_non_padded_volumes: true
            password: Ericsson123@
            gateway_ip: "192.168.10.23"
            gateway_user: admin
            gateway_password: Ericsson123@
            gateway_port: 443



4. Deploy vxflexos sdc (+cluster):

   YCCM=/your/cee/config-model

   ansible-playbook \
     -i $YCCM/hosts \
     -i inventory/vxflexos.yml  \
     vxflexos-deploy.yml


5. Deploy cinder backend:

   YCCM=/your/cee/config-model

   ansible-playbook \
     -i $YCCM/hosts/ \
     -i inventory/cinder_backends.yml  \
     -i $YCCM/system/openstack/inventory.yml \
     -e @$YCCM/system/openstack/globals.yml \
     -e @$YCCM/system/openstack/passwords.yml \
     -e kolla_action=deploy \
     openstack/kolla-ansible/ansible/site.yml \
     --tags cinder
