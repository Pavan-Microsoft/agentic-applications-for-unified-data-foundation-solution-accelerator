data "azapi_resource" "account" {
  type                   = "Microsoft.CognitiveServices/accounts@2025-12-01"
  parent_id              = "/subscriptions/${var.subscription_id}/resourceGroups/${var.resource_group_name}"
  name                   = var.name
  response_export_values = ["properties.endpoints", "properties.endpoint", "identity.principalId"]
}
data "azapi_resource" "project" {
  type                   = "Microsoft.CognitiveServices/accounts/projects@2025-12-01"
  parent_id              = data.azapi_resource.account.id
  name                   = var.project_name
  response_export_values = ["properties.endpoints", "identity.principalId"]
}
