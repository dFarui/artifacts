#!/usr/bin/env python

################################################################################
#                                                                              #
# COPYRIGHT Ericsson 2020                                                      #
#                                                                              #
# The copyright to the computer program(s) herein is the property of Ericsson  #
# Inc. The programs may be used and/or copied only with written permission     #
# from Ericsson Inc. or in accordance with the terms and conditions stipulated #
# in the agreement/contract under which the program(s) have been supplied.     #
#                                                                              #
################################################################################

from ansible.module_utils.basic import AnsibleModule
from distutils.version import StrictVersion

import difflib
import docker
import json
import time
import xml.etree.ElementTree as ET

DOCUMENTATION = '''
---
module: pacemaker
short_description: >
  Module for managing containarized Pacemaker and its resources.
description:
  - TODO
options:
 TODO
'''

EXAMPLES = '''TODO'''

class NameValuePair(object):
    element_name = "nvpair"
    def __init__(self, name, value):
        self.name = name
        self.value = value

    def get_name(self):
        return self.name

    @classmethod
    def from_element(cls, element):
        return cls(element.attrib['name'], element.attrib['value'])

    def get_element(self, resource_name=None, attribute_type=None):
        element_id = '-'.join(filter(None, [resource_name, attribute_type,
                                            self.name]))
        attributes = {
            'id': element_id,
            'name': self.name,
            'value': self.value
        }
        return ET.Element('nvpair', attributes)

    def __iter__(self):
        class_attribute_order = ['name', 'value']
        for attribute in class_attribute_order:
            yield getattr(self, attribute)

    def __repr__(self):
        return f"NameValuePair{tuple(self)}"

    def __hash__(self):
        return hash(tuple(self))

    def __eq__(self, other):
        if isinstance(other, NameValuePair):
            return tuple(self) == tuple(other)


class ResourceOperation(object):
    element_name = "op"
    def __init__(self, name, interval, timeout=None, role=None, on_fail=None,
                 enabled=None):
        self.name = name               # Mandatory
        self.interval = interval       # Mandatory
        self.timeout = timeout         # Optional
        self.enabled = enabled         # Optional
        self.role = role               # Optional
        self.on_fail = on_fail         # Optional

    def get_name(self):
        return self.name

    @classmethod
    def from_element(cls, element):
        return cls(element.attrib['name'], element.attrib['interval'],
                   element.attrib.get('timeout'), element.attrib.get('role'),
                   element.attrib.get('on_fail'),
                   element.attrib.get('enabled'))

    def get_element(self, resource_name=""):
        attributes = {
            'id': f"{resource_name}-{self.name}-{self.interval}",
            'name': self.name,
            'interval': self.interval
        }
        if self.timeout: attributes['timeout'] = self.timeout
        if self.role: attributes['role'] = self.role
        if self.on_fail: attributes['on_fail'] = self.on_fail
        if isinstance(self.enabled, bool): attributes['enabled'] = self.enabled
        return ET.Element('op', attributes)

    def __iter__(self):
        class_attribute_order = ['name', 'interval', 'timeout', 'role',
                                 'on_fail', 'enabled']
        for attribute in class_attribute_order:
            yield getattr(self, attribute)

    def __repr__(self):
        return f"ResourceOperation{tuple(self)}"

    def __hash__(self):
        return hash(tuple(self))

    def __eq__(self, other):
        if isinstance(other, ResourceOperation):
            return tuple(self) == tuple(other)
        elif isinstance(other, ET.Element):
            return (tuple(self) == (other.attrib['name'],
                other.attrib['interval'], other.attrib.get('timeout'),
                other.attrib.get('role'), other.attrib.get('on_fail'),
                other.attrib.get('enabled')))


def get_docker_client():
    return docker.APIClient


class PacemakerWorker(object):
    def __init__(self, module):
        self.module = module
        self.params = self.module.params
        self.changed = False
        self.failed = False
        self.result = {}
        self.container = self.params.get('container', 'pacemaker')
        self.dc = get_docker_client()()

    def exec(self, command, stderr=False):
        job = self.dc.exec_create(self.container, command, stderr=stderr)
        return self.dc.exec_start(job).decode("utf-8")

    def crmsh(self, command, stderr=False):
        return self.exec(f'crm {command}', stderr)

    def cib(self, scope=None, stderr=False):
        arg_scope = f'--scope={scope}' if scope else ''
        return self.exec(f'cibadmin --query {arg_scope}', stderr)

    def set_property(self):
        value = self.params.get('value')
        actual = self.get_property()
        if self.get_property() != value:
            property = self.params.get('property')
            result = self.crmsh(f'configure property {property}={value}')
            self.result['rc'] = 0
            self.result['stdout'] = result
            self.changed = True
            return result

    def get_property(self):
        property = self.params.get('property')
        result = self.crmsh(f'configure get_property {property}').rstrip()
        self.result['rc'] = 0
        self.result['stdout'] = result
        return result

    def online_members(self):
        cib = ET.fromstring(self.cib())
        count = len([1 for node_state
                     in cib.findall(f"./status/node_state[@crmd='online']")
                     if node_state.attrib.get('join') == "member"])
        self.result['count'] = count
        return count

    def add_node(self):
        node_name = self.params.get('name')
        node_type = self.params.get('type')
        cib = ET.fromstring(self.cib())

        # Check whether the node already exists in the CIB
        nodes = cib.findall(f"./configuration/nodes/node[@id='{node_name}']")
        if len(nodes) == 1 and nodes[0].attrib.get('type') == node_type: return

        # The given node isn't defined yet, let's add it
        self.changed = True
        result = self.exec(f'cibadmin --modify --allow-create --scope nodes -X '
                           f'\'<node id="{node_name}" type="{node_type}" '
                           f'uname="{node_name}"/>\'')
        return result

    def get_node_attribute(self):
        node_name = self.params.get('node')
        attribute = self.params.get('attribute')
        cib = ET.fromstring(self.cib())
        nvpairs = cib.findall(f"./configuration/nodes"
                              f"/node[@uname='{node_name}']"
                              f"/instance_attributes"
                              f"/nvpair[@name='{attribute}']")
        result = nvpairs[0].attrib.get('value') if len(nvpairs) == 1 else None
        self.result["value"] = result
        return result

    def set_node_attribute(self):
        value = self.params.get('value')

        # Check whether the given node attribute already set
        if self.get_node_attribute() == value:
            return

        node_name = self.params.get('node')
        attribute = self.params.get('attribute')
        lifetime = self.params.get('lifetime')
        if lifetime == 'reboot':
            result = self.exec(f'crm_attribute -N {node_name} -l reboot'
                               f' --name {attribute} -v {value}')
        else:
            result = self.crmsh(f'node attribute {node_name} set '
                                f'{attribute} {value}')
        self.result["stdout"] = result
        self.result["value"] = value
        self.changed = True
        return result

    def del_resource(self):
         resource_name = self.params.get('name')
         cib = ET.fromstring(self.cib())
         if len(cib.findall(f"./configuration/resources"
                            f"/*[@id='{resource_name}']")) != 1:
             return

         self.crmsh(f'resource stop {resource_name}')

         # Wait until the resource is stopped
         while True:
             result = self.crmsh(f'resource status {resource_name}',
                                 stderr=True)
             if result == f"resource {resource_name} is NOT running\n":
                 break
             time.sleep(2)

         self.crmsh(f'configure delete {resource_name}')

    def resource_exists(self):
        resource_name = self.params.get('name')
        self.changed = False
        cib = ET.fromstring(self.cib())
        if len(cib.findall(f"./configuration/resources"
                           f"//*[@id='{resource_name}']")) == 1:
            return True
        return False

    def add_resource(self):
        resource_type = self.params.get('type')
        resource_name = self.params.get('name')
        resource_agent = self.params.get('agent')
        recreate = self.params.get('recreate', False)

        # Check whether the given resource already exists
        cib = ET.fromstring(self.cib("resources"))
        cib_text = ET.tostring(cib, encoding='utf-8').decode()
        matching_resources = cib.findall(f".//*[@id='{resource_name}']")

        if len(matching_resources) == 1 and not recreate:
            # Resource exists
            rsc = matching_resources[0]

            resource_elements = [
                ('parameter', 'param', 'instance_attributes', NameValuePair),
                ('meta', 'meta', 'meta_attributes', NameValuePair),
                ('operation', 'operation', 'operations', ResourceOperation)
            ]
            for (config_name, config_key, cib_element,
                 element_class) in resource_elements:
                element_root = cib.find(f".//*[@id='{resource_name}']"
                                        f"/{cib_element}")
                elements = rsc.findall(f"./{cib_element}"
                                       f"/{element_class.element_name}")
                actual = set(
                    element_class.from_element(element) for element
                    in elements
                )

                configuration = self.params.get(config_name, dict())
                configuration = configuration if configuration else dict()

                desired = set()
                for name, value in configuration.items():
                    values = value if isinstance(value, list) else [value]
                    for val in values:
                        if element_class == ResourceOperation:
                            attributes = val.copy()
                            if 'interval' in attributes.keys():
                                attributes.pop('interval')
                            elem = element_class(
                                name,
                                val.get('interval', '0'),
                                **attributes
                            )
                        else:
                            elem = element_class(name, str(val))
                        desired.add(elem)

                differences = desired ^ actual

                # Filter out optional "target-role" meta attribute
                optionals = [opt for opt in differences
                             if opt.get_name() == "target-role"]
                for optional in optionals:
                    required = [req for req in desired
                                if req.get_name() == optional.get_name()]
                    if optional in actual and not required:
                        differences.remove(optional)

                for difference in differences:
                    self.changed = True
                    if difference in actual:
                        # Element to be removed
                        matching_elements = cib.findall(
                            f".//*[@id='{resource_name}']/{cib_element}"
                            f"/{element_class.element_name}"
                            f"[@name='{difference.get_name()}']"
                        )
                        for element in matching_elements:
                            if difference == element:
                                element_root.remove(element)
                    else:
                        # Element to be added
                        params = (
                            (resource_name, cib_element)
                            if isinstance(difference, NameValuePair)
                            else ([resource_name])
                        )
                        element_root.append(
                            difference.get_element(*params)
                        )


            # Calculate CIB difference
            cib_resources_xml_updated = ET.tostring(cib,
                                                    encoding='utf-8').decode()
            diff = ''.join(str(e) for e in difflib.unified_diff(
                cib_text.splitlines(True),
                cib_resources_xml_updated.splitlines(True)
            ))
            self.result['diff'] = diff

            if self.changed:
                # Replace the resources section of CIB with the updated XML
                job = self.dc.exec_create(
                    "pacemaker",
                    "cibadmin --xml-pipe --replace --scope=resources",
                    stdin=True
                )
                sock = self.dc.exec_start(job, socket=True)
                sock._sock.sendall(ET.tostring(cib, encoding='utf-8'))
                sock._sock.sendall(b'\n')
                sock.close()
            return
        elif len(matching_resources) == 1 and recreate:
            self.del_resource()

        # Resource parameters
        parameters = self.params.get('parameter')
        resource_parameters = ""
        if type(parameters) is dict:
            parameters = " ".join([f'{k}="{v}"'for k, v in parameters.items()])
            resource_parameters = f"params {parameters}"

        # Resource operations
        operations = self.params.get('operation')
        resource_operations = list()
        if type(operations) is dict:
            for operation, properties in operations.items():
                attributes = (properties if type(properties) is list
                              else [properties])
                for attribute in attributes:
                    attributes_str = " ".join([f'{k}="{v}"' for k, v
                                               in attribute.items()])
                    resource_operations.append(f"op {operation}"
                                               f" {attributes_str}")
        resource_operations = " ".join(resource_operations)

        # Resource Meta attributes
        meta = self.params.get('meta')
        resource_meta = ""
        if type(meta) is dict:
            meta_attributes = " ".join([ f"{k}={v}" for k,v in meta.items() ])
            resource_meta = f"meta {meta_attributes}"

        result = self.crmsh(f'configure {resource_type} {resource_name} '
                            f'{resource_agent} {resource_parameters} '
                            f'{resource_operations} {resource_meta}')
        self.result["stdout"] = result
        self.changed = True
        return result

    def add_location_constraint(self):
        location_name = self.params.get('name')

        # Check whether the location constraint already exists
        cib = ET.fromstring(self.cib())
        if len(cib.findall(f"./configuration/constraints"
                           f"/*[@id='{location_name}']")) == 1:
            return

        resource_name = self.params.get('resource')
        attribute = self.params.get('attribute', "")
        if type(attribute) is dict:
            attribute = " ".join([f'{k}="{v}"' for k, v
                                  in attribute.items()])
        rules = self.params.get('rules')
        result = self.crmsh(f'configure location {location_name} '
                            f'{resource_name} {attribute} {rules}')
        self.result["stdout"] = result
        self.changed = True
        return result

    def get_resource_status(self):
        resource_name = self.params.get('name')
        command = "resource status"
        status = self.crmsh(command, stderr=True)
        result = "None"
        if type(status) == str:
            lines = status.splitlines()
            for line in lines:
                if line.find(resource_name) >= 0:
                    if line.find("Stopped (disabled)") >= 0:
                        result = "Stopped"
                    elif line.find("Started (disabled)") >= 0:
                        result = "Disabled"
                    elif line.find("Started") >= 0:
                        result = "Started"
                    elif line.find("FAILED") >= 0:
                        result = "Failed"
        self.result["stdout"] = result
        self.changed = False
        return result

    def start_resource(self):
        resource_name = self.params.get('name')
        command = "resource start {}".format(resource_name)
        state = self.crmsh(command, stderr=True)
        result = "{} return {}".format(command, state)
        self.result["stdout"] = result
        self.changed = True
        return result

    def stop_resource(self):
        resource_name = self.params.get('name')
        command = "resource stop {}".format(resource_name)
        state = self.crmsh(command, stderr=True)
        result = "{} return {}".format(command, state)
        self.result["stdout"] = result
        self.changed = True
        return result

    def get_resource_name(self):
        resource_param = self.params.get('parameter')
        hostname = resource_param.get('hostname')
        result = 'None'
        rsc = ET.fromstring(self.cib("resources"))
        # find resource name
        crm = []
        for prim in rsc.findall('./primitive[@id]'):
            for ms in prim.findall(f"./meta_attributes/"
                                   f"nvpair[@value='{hostname}']"):
                crm.append(prim.attrib['id'])
        # create result
        if len(crm) == 1:
            result = crm[0]
        self.result["stdout"] = result
        self.changed = False
        return result

    def update_resource_param(self):
        resource_name = self.params.get('name')
        param = self.params.get('parameter')
        if type(param) != dict:
            result = "input is not a dict {}".format(param)
            self.result["stdout"] = result
            self.changed = False
            return result
        result = ""
        keys = param.keys()
        for key in keys:
            command = "resource param {} set {} {}".format(resource_name,
                                                           key,
                                                           param[key])
            self.crmsh(command)
            result = "{}{}; ".format(result, command)

        self.result["stdout"] = result
        self.changed = True
        return result


def main():
    specs = dict(
      action=dict(required=True, type='str'),
      property=dict(required=False, type='str'),
      value=dict(required=False, type='str'),
      name=dict(required=False, type='str'),
      type=dict(required=False, type='str'),
      node=dict(required=False, type='str'),
      attribute=dict(required=False, type='str'),
      operation=dict(required=False, type='dict'),
      parameter=dict(required=False, type='dict'),
      meta=dict(required=False, type='dict'),
      resource=dict(required=False, type='str'),
      agent=dict(required=False, type='str'),
      rules=dict(required=False, type='str'),
      lifetime=dict(required=False, type='str'),
      recreate=dict(required=False, type='bool'),
    )
    module = AnsibleModule(argument_spec=specs, bypass_checks=True)

    pw = PacemakerWorker(module)
    result = bool(getattr(pw, module.params.get('action'))())
    module.exit_json(changed=pw.changed, result=result, **pw.result)


if __name__ == "__main__":
    main()
