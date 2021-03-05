def generate_rsyslog_function_body(parameters_mapping):
    return '\n'.join(
        '    {}="{}"'.format(parameter_name, parameter_value)
        for parameter_name, parameter_value in parameters_mapping.items()
    )


class FilterModule(object):

    def filters(self):
        return {
            'is_any_rsyslog_log_generator_forwarding_logs':
                self.is_any_rsyslog_log_generator_forwarding_logs,
            'is_any_service_logging_to_file_directly':
                self.is_any_service_logging_to_file_directly,
            'is_local_logging_rule_for_service_needed':
                self.is_local_logging_rule_for_service_needed,
            'is_remote_logging_rule_for_service_needed':
                self.is_remote_logging_rule_for_service_needed,
            'to_rsyslog_action':
                self.to_rsyslog_action,
            'to_rsyslog_template':
                self.to_rsyslog_template,
            'with_source_type':
                self.with_source_type,
        }

    def is_any_rsyslog_log_generator_forwarding_logs(self, hostvars, nodes_to_skip):
        return True
#       TODO
#        no_log_forward_node_logging_details = {'forward_logs_to': 'nowhere'}
#        return any(
#            node_properties.get(
#                'logging_details',
#                no_log_forward_node_logging_details
#            )['forward_logs_to'] == 'internalAggregator'
#            for node_name, node_properties in hostvars.items()
#            if node_name not in nodes_to_skip
#        )

    def is_any_service_logging_to_file_directly(self, services):
        return any(
            x['enabled'] for x in
            self.with_source_type(services, 'file').values()
        )

    def is_local_logging_rule_for_service_needed(
            self,
            service_component_to_nodes_map,
            node_name,
            *service_names
    ):
        return any(
            node_name in service_component_to_nodes_map.get(service_name, [])
            for service_name in service_names
        )

    def is_remote_logging_rule_for_service_needed(
            self,
            service_component_to_nodes_map,
            log_aggregator_nodes,
            *service_names
    ):
        return any(
            len(
                set(service_component_to_nodes_map.get(service_name, [])) -
                set(log_aggregator_nodes)
            ) > 0
            for service_name in service_names
        )

    def to_rsyslog_template(self, parameters_mapping):
        return 'template(\n{}\n)'.format(
            generate_rsyslog_function_body(parameters_mapping)
        )

    def to_rsyslog_action(self, parameters_mapping):
        return 'action(\n{}\n)'.format(
            generate_rsyslog_function_body(parameters_mapping)
        )

    def with_source_type(self, services, source_type):
        return {
            key: value
            for key, value in services.items()
            if value['logging_rule_input']['source_type'] == source_type
        }
