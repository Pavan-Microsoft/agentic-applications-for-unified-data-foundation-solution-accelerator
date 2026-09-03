locals { name = coalesce(var.name, "log-${var.solution_name}") }
resource "azurerm_log_analytics_workspace" "main" {
  name                = local.name
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = var.tags
  retention_in_days   = var.retention_in_days
  sku                 = var.sku_name
  identity { type = var.identity.type }
}
