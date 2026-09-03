resource "azurerm_fabric_capacity" "main" {
  name                   = var.name
  resource_group_name    = var.resource_group_name
  location               = var.location
  administration_members = var.admin_members
  tags                   = var.tags
  sku {
    name = var.sku_name
    tier = "Fabric"
  }
}
