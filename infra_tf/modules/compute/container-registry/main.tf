locals { name = coalesce(var.name, replace("cr${var.solution_name}", "-", "")) }
resource "azurerm_container_registry" "main" {
  name                          = local.name
  resource_group_name           = var.resource_group_name
  location                      = var.location
  tags                          = var.tags
  sku                           = var.sku
  admin_enabled                 = var.admin_user_enabled
  public_network_access_enabled = var.public_network_access == "Enabled"
  data_endpoint_enabled         = false
  network_rule_bypass_option    = "AzureServices"
  export_policy_enabled         = lower(var.export_policy_status) == "enabled"
  zone_redundancy_enabled       = false
  identity { type = var.identity.type }
}
