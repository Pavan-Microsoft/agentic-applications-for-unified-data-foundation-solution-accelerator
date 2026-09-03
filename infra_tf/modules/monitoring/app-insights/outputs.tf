output "resource_id" {
  value = azurerm_application_insights.main.id
}
output "name" {
  value = azurerm_application_insights.main.name
}
output "instrumentation_key" {
  value     = azurerm_application_insights.main.instrumentation_key
  sensitive = true
}
output "connection_string" {
  value     = azurerm_application_insights.main.connection_string
  sensitive = true
}
output "application_id" {
  value = azurerm_application_insights.main.app_id
}
