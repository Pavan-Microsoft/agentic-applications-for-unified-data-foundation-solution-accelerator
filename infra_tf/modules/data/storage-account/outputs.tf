output "resource_id" {
  value = azurerm_storage_account.main.id
}
output "name" {
  value = azurerm_storage_account.main.name
}
output "blob_endpoint" {
  value = azurerm_storage_account.main.primary_blob_endpoint
}
output "service_endpoints" {
  value = { blob = azurerm_storage_account.main.primary_blob_endpoint, file = azurerm_storage_account.main.primary_file_endpoint, queue = azurerm_storage_account.main.primary_queue_endpoint, table = azurerm_storage_account.main.primary_table_endpoint }
}
