CREATE TABLE IF NOT EXISTS `h3c_servicecontexts` (
  `id` varchar(36) NOT NULL,
  `tenant_id` varchar(255) DEFAULT NULL,
  `name` varchar(255) DEFAULT NULL,
  `description` varchar(255) DEFAULT NULL,
  `type` enum('router','network','subnet','port') NOT NULL,
  `in_chain` tinyint(1) DEFAULT NULL,
  PRIMARY KEY (`id`),
  CONSTRAINT `CONSTRAINT_1` CHECK (`in_chain` in (0,1))
);

CREATE TABLE IF NOT EXISTS `h3c_serviceinsertions` (
  `id` varchar(36) NOT NULL,
  `tenant_id` varchar(255) DEFAULT NULL,
  `name` varchar(255) DEFAULT NULL,
  `source_context_type` varchar(255) DEFAULT NULL,
  `source_context_id` varchar(255) DEFAULT NULL,
  `destination_context_type` varchar(255) DEFAULT NULL,
  `destination_context_id` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`id`)
);

CREATE TABLE IF NOT EXISTS `h3c_servicenodes` (
  `id` varchar(36) NOT NULL,
  `tenant_id` varchar(255) DEFAULT NULL,
  `service_type` varchar(255) DEFAULT NULL,
  `service_instance_id` varchar(255) DEFAULT NULL,
  `insertion_id` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `insertion_id` (`insertion_id`),
  CONSTRAINT `h3c_servicenodes_ibfk_1` FOREIGN KEY (`insertion_id`) REFERENCES `h3c_serviceinsertions` (`id`) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS `h3c_loadbalancers` (
  `id` varchar(36) NOT NULL,
  `tenant_id` varchar(255) DEFAULT NULL,
  `pool_id` varchar(255) DEFAULT NULL,
  `name` varchar(255) DEFAULT NULL,
  `description` varchar(255) DEFAULT NULL,
  `mode` enum('GATEWAY','SERVICE_CHAIN','VIP_ROUTE','CGSR') NOT NULL,
  PRIMARY KEY (`id`)
);

CREATE TABLE IF NOT EXISTS `h3c_l3_vxlan_allocations` (
  `vxlan_vni` int(11) NOT NULL,
  `router_id` varchar(255) DEFAULT NULL,
  `allocated` tinyint(1) NOT NULL DEFAULT 0,
  PRIMARY KEY (`vxlan_vni`),
  KEY `ix_h3c_l3_vxlan_allocations_allocated` (`allocated`),
  CONSTRAINT `CONSTRAINT_1` CHECK (`allocated` in (0,1))
);
