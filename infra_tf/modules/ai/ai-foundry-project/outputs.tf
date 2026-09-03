output "resource_id" {
  value = azapi_resource.account.id
}
output "name" {
  value = azapi_resource.account.name
}
output "endpoint" {
  value = azapi_resource.account.output.properties.endpoints["OpenAI Language Model Instance API"]
}
output "cognitive_services_endpoint" {
  value = azapi_resource.account.output.properties.endpoint
}
output "azure_open_ai_cu_endpoint" {
  value = azapi_resource.account.output.properties.endpoints["Content Understanding"]
}
output "principal_id" {
  value = azapi_resource.account.output.identity.principalId
}
output "project_resource_id" {
  value = azapi_resource.project.id
}
output "project_name" {
  value = azapi_resource.project.name
}
output "project_endpoint" {
  value = azapi_resource.project.output.properties.endpoints["AI Foundry API"]
}
output "project_identity_principal_id" {
  value = azapi_resource.project.output.identity.principalId
}
