locals { name = coalesce(var.name, "asp-${var.solution_name}") }
resource "azurerm_service_plan" "main" {
  name                   = local.name
  resource_group_name    = var.resource_group_name
  location               = var.location
  tags                   = var.tags
  os_type                = var.reserved ? "Linux" : "Windows"
  sku_name               = var.sku_name
  worker_count           = var.sku_capacity
  zone_balancing_enabled = var.zone_redundant
}
