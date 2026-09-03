output "resource_id" {
  value = azurerm_cosmosdb_account.main.id
}
output "name" {
  value = azurerm_cosmosdb_account.main.name
}
output "endpoint" {
  value = azurerm_cosmosdb_account.main.endpoint
}
output "database_name" {
  value = azurerm_cosmosdb_sql_database.main.name
}
output "container_name" {
  value = var.containers[0].name
}
