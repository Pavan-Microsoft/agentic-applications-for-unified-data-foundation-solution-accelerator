output "resource_id" {
  value = module.search_service_update.resource_id
}
output "name" {
  value = local.name
}
output "endpoint" {
  value = "https://${local.name}.search.windows.net"
}
output "identity_principal_id" {
  value = module.search_service_update.system_assigned_mi_principal_id
}
