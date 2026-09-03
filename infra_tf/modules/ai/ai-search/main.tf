locals { name = coalesce(var.name, "srch-${var.solution_name}") }
module "search_service_update" {
  source                = "../ai-search-identity"
  subscription_id       = var.subscription_id
  resource_group_name   = var.resource_group_name
  name                  = local.name
  location              = var.location
  tags                  = var.tags
  sku_name              = var.sku_name
  replica_count         = var.replica_count
  partition_count       = var.partition_count
  hosting_mode          = var.hosting_mode
  semantic_search       = var.semantic_search
  disable_local_auth    = var.disable_local_auth
  auth_options          = var.auth_options
  network_rule_set      = var.network_rule_set
  identity              = var.identity
  public_network_access = var.public_network_access
}
