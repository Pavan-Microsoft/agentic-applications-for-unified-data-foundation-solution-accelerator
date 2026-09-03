locals {
  name         = coalesce(var.name, "aif-${var.solution_name}")
  project_name = coalesce(var.project_name, "proj-${var.solution_name}")
}
resource "azapi_resource" "account" {
  type                      = "Microsoft.CognitiveServices/accounts@2025-12-01"
  name                      = local.name
  parent_id                 = "/subscriptions/${var.subscription_id}/resourceGroups/${var.resource_group_name}"
  location                  = var.location
  tags                      = var.tags
  schema_validation_enabled = false
  identity { type = var.identity.type }
  body = {
    kind = "AIServices"
    sku  = { name = var.sku_name }
    properties = {
      allowProjectManagement = var.allow_project_management
      customSubDomainName    = local.name
      networkAcls            = { defaultAction = var.network_acls_default_action, virtualNetworkRules = [], ipRules = [] }
      publicNetworkAccess    = var.public_network_access
      disableLocalAuth       = var.disable_local_auth
    }
  }
  response_export_values = ["properties.endpoints", "properties.endpoint", "identity.principalId"]
}
resource "azapi_resource" "project" {
  type                      = "Microsoft.CognitiveServices/accounts/projects@2025-12-01"
  name                      = local.project_name
  parent_id                 = azapi_resource.account.id
  location                  = var.location
  schema_validation_enabled = false
  identity { type = var.identity.type }
  body = {
    kind       = "AIServices"
    properties = {}
  }
  response_export_values = ["properties.endpoints", "identity.principalId"]
}
