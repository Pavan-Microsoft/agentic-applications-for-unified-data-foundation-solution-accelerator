locals { name = coalesce(var.name, "cosmos-${var.solution_name}") }
resource "azurerm_cosmosdb_account" "main" {
  name                             = local.name
  resource_group_name              = var.resource_group_name
  location                         = var.location
  tags                             = var.tags
  offer_type                       = "Standard"
  kind                             = "GlobalDocumentDB"
  local_authentication_enabled     = false
  automatic_failover_enabled       = false
  multiple_write_locations_enabled = false
  capabilities { name = "EnableServerless" }
  consistency_policy { consistency_level = "Session" }
  geo_location {
    location          = var.location
    failover_priority = 0
    zone_redundant    = false
  }
  identity { type = var.identity.type }
}
resource "azurerm_cosmosdb_sql_database" "main" {
  name                = var.database_name
  resource_group_name = var.resource_group_name
  account_name        = azurerm_cosmosdb_account.main.name
}
resource "azurerm_cosmosdb_sql_container" "main" {
  for_each            = { for container in var.containers : container.name => container }
  name                = each.value.name
  resource_group_name = var.resource_group_name
  account_name        = azurerm_cosmosdb_account.main.name
  database_name       = azurerm_cosmosdb_sql_database.main.name
  partition_key_paths = [each.value.partition_key_path]
}
