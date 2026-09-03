locals { name = coalesce(var.name, "appi-${var.solution_name}") }
resource "azurerm_application_insights" "main" {
  name                       = local.name
  resource_group_name        = var.resource_group_name
  location                   = var.location
  tags                       = var.tags
  workspace_id               = var.workspace_resource_id
  application_type           = var.application_type
  retention_in_days          = var.retention_in_days
  ip_masking_enabled         = !var.disable_ip_masking
  internet_ingestion_enabled = true
  internet_query_enabled     = true
}
