# Make Artifacts
---

## rpmbuild

## H3C storage plugins
### flavors.yaml
```yaml
# cic domain
  - name: pacemaker_main_controller
    cgroup: container
    manager: docker
    customProperties:
      domainName: main_controller_domain
# cinderA domain
  - name: pacemaker_vcontroller_az1
    cgroup: container
    manager: docker
    customProperties:
      domainName: vcontroller_az1_domain
# cinderB domain
  - name: pacemaker_vcontroller_az2
    cgroup: container
    manager: docker
    customProperties:
      domainName: vcontroller_az2_domain
# cinderA storage pool info
- name: generic_h3c_storageA
    customProperties:
      vendor: h3c
      user: XXXX
      password: XXXX
      onestor_diskpool: DiskPoolA
      onestor_poolname: BlockPoolA
      onestor_nodepool: NodePool
      onestor_handy_ip: XXXXX
      onestor_block_service_ip: XXXXX
      onestor_ip_addr: 
      volume_backend_name: H3C_onestor
      backend_host: cinderA
      iqn: XXXX
# cinderB storage pool info
- name: generic_h3c_storageB
    customProperties:
      vendor: h3c
      user: XXXX
      password: XXXX
      onestor_diskpool: DiskPoolB
      onestor_poolname: BlockPoolB
      onestor_nodepool: NodePool
      onestor_handy_ip: XXXXX
      onestor_block_service_ip: XXXXX
      onestor_ip_addr: 
      volume_backend_name: H3C_onestor
      backend_host: cinderB
      iqn: XXXX
# cic storage info
  - name: generic_h3c_storage
    customProperties:
      vendor: h3c
      user: 
      password: 
      onestor_diskpool: 
      onestor_poolname: 
      onestor_nodepool: 
      onestor_handy_ip:
      onestor_block_service_ip: XXXXX
      volume_backend_name:
      backend_host:  
      iqn: XXXXX
```

### host_profile.yaml
```yaml
  - name: cicNode
    interfaceAssignment: controller
    diskAssignment: controller-disks
    hostConfigAssignment: controller-host-config
    memoryAssignment: controller_memory
    controlGroupScheme: controller
    hostService: host_services_controller
    # cic storage plugin
    hostSoftware: CSS-SDN-Storage-v1
  - name: cinderVolumeA
    interfaceAssignment: cinderVolumeA
    diskAssignment: cinderA-disks
    hostConfigAssignment: vm-host-config
    controlGroupScheme: controlGroupsCinderA
    hostService: host_services_cinder
    # cinderA storage plugin
    hostSoftware: hostOS-v2
    type: virtualMachine
    vmResources:
      cpu: 18
      memGiB: 112
  - name: cinderVolumeB
    interfaceAssignment: cinderVolumeB
    diskAssignment: cinderB-disks
    hostConfigAssignment: vm-host-config
    controlGroupScheme: controlGroupsCinderB
    hostService: host_services_cinder
    # cinderB storage plugin
    hostSoftware: hostOS-v2
    type: virtualMachine
    vmResources:
      cpu: 12
      memGiB: 60
  - name: compute_4A_no_vxlan
    interfaceAssignment: compute-4A-no-vxlan
    diskAssignment: compute-disks
    hostConfigAssignment: compute-host-config
    memoryAssignment: compute_memory
    controlGroupScheme: compute
    hostService: host_services_compute
    # compute storage plugin
    hostSoftware: CSS-SDN-Storage-v1
```

### services.yaml
```yaml
  - name: cinderVolumeB
    serviceComponents:
      - name: pacemaker
        flavor: pacemaker_vcontroller_az2
      - name: h3c-storage
        flavor: generic_h3c_storageB
...
  - name: cinderVolumeA
    serviceComponents:
      - name: pacemaker
        flavor: pacemaker_vcontroller_az1
      - name: h3c-storage
        flavor: generic_h3c_storageA
...
  - name: openstack_controller
    serviceComponents:
      - name: h3c-storage
        flavor: generic_h3c_storage
      - name: pacemaker
        flavor: pacemaker_main_controller
...
  - name: openstack_computes
    serviceComponents:
      - name: h3c-storage
        flavor: generic_h3c_storage
```

### software.yaml
```yaml
  - name: h3c-storage-plugin
    versions:
      - version: R1A01
        url: '/repos/CXC008646001-R1A01-E3307P01L02'
    type: rpm-md
```

### softwareAllocation.yaml
```yaml
  - name: hostOS-v2
    software:
      - name: hostos
        version: sles15sp2
      - name: cee-host-extras
        version: sles15sp2
      - name: h3c-storage-plugin
        version: R1A01

  - name: CSS-SDN-Storage-v1
    software:
      - name: ericsson-css
        version: 1.0
      - name: hostos
        version: sles15sp2
      - name: cee-host-extras
        version: sles15sp2 
      - name: h3c-storage-plugin
        version: R1A01
```
## kolla-ansible 

## command
```shell
# auto integration storage command 
ansible-playbook -i orchestrator/ansible/hosts -i system/openstack/inventory.yml -e @system/openstack/globals.yml -e @system/openstack/passwords.yml orchestrator/ansible/h3c-storage-deploy.yaml
```
