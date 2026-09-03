resource "azurerm_cognitive_deployment" "main" {
  name                 = var.deployment_name
  cognitive_account_id = "/subscriptions/${var.subscription_id}/resourceGroups/${var.resource_group_name}/providers/Microsoft.CognitiveServices/accounts/${var.ai_services_account_name}"
  rai_policy_name      = var.rai_policy_name
  model {
    format  = var.model_format
    name    = var.model_name
    version = var.model_version != "" ? var.model_version : null
  }
  sku {
    name     = var.sku_name
    capacity = var.sku_capacity
  }
}
