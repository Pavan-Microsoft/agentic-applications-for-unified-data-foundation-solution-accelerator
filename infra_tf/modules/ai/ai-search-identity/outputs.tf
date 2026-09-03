output "system_assigned_mi_principal_id" {
  value = azapi_resource.main.output.identity.principalId
}
output "resource_id" {
  value = azapi_resource.main.id
}
