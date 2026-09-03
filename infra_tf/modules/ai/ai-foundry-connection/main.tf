locals {
  connection_name = coalesce(var.connection_name, lower("${var.category}-connection-${var.solution_name}"))
  properties      = merge({ category = var.category, target = var.target, authType = var.auth_type, isSharedToAll = var.is_shared_to_all, metadata = var.metadata, useWorkspaceManagedIdentity = var.use_workspace_managed_identity }, var.is_default ? { isDefault = true } : {}, var.credentials_key != "" ? { credentials = { key = var.credentials_key } } : {})
}
resource "azapi_resource" "connection" {
  type                      = "Microsoft.CognitiveServices/accounts/projects/connections@2025-12-01"
  name                      = local.connection_name
  parent_id                 = "/subscriptions/${var.subscription_id}/resourceGroups/${var.resource_group_name}/providers/Microsoft.CognitiveServices/accounts/${var.ai_services_account_name}/projects/${var.project_name}"
  schema_validation_enabled = false
  body                      = { properties = local.properties }
  lifecycle { ignore_changes = [body] }
}
