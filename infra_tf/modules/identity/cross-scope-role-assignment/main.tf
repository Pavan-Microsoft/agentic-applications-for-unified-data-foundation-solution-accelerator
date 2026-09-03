resource "azurerm_role_assignment" "main" {
  name               = var.role_assignment_name
  scope              = "/subscriptions/${var.subscription_id}/resourceGroups/${var.resource_group_name}/providers/Microsoft.CognitiveServices/accounts/${var.ai_foundry_name}"
  role_definition_id = var.role_definition_id
  principal_id       = var.principal_id
  principal_type     = var.principal_type
}
