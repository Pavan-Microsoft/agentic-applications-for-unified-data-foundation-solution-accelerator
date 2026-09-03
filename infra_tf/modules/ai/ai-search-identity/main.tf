resource "azapi_resource" "main" {
  type                      = "Microsoft.Search/searchServices@2025-05-01"
  name                      = var.name
  parent_id                 = "/subscriptions/${var.subscription_id}/resourceGroups/${var.resource_group_name}"
  location                  = var.location
  tags                      = var.tags
  schema_validation_enabled = false
  identity { type = var.identity.type }
  body = {
    sku = { name = var.sku_name }
    properties = {
      replicaCount        = var.replica_count
      partitionCount      = var.partition_count
      hostingMode         = var.hosting_mode
      semanticSearch      = var.semantic_search
      disableLocalAuth    = var.disable_local_auth
      publicNetworkAccess = var.public_network_access
      authOptions         = length(keys(var.auth_options)) > 0 ? var.auth_options : null
      networkRuleSet      = length(keys(var.network_rule_set)) > 0 ? var.network_rule_set : null
    }
  }
  response_export_values = ["identity.principalId"]
}
