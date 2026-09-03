locals {
  roles = {
    azure_ai_user = "53ca6127-db72-4b80-b1b0-d745d6d5456d", cognitive_services_user = "a97b65f3-24c7-4388-baec-2e87135dc908", openai_user = "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd", search_reader = "1407120a-92aa-4202-b7e9-c0e197c71c8f", search_contributor = "8ebe5a00-799e-43f5-93ac-243d3dce84a7", search_service_contributor = "7ca78c08-252a-4471-8644-bb5ff32d4ba0", storage_contributor = "ba92f5b4-2d11-453d-a403-e96b0029c9fe", storage_reader = "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1", acr_pull = "7f951dda-4ed3-4680-a7ca-43fe172d538d"
  }
  role_ids               = { for key, value in local.roles : key => "/subscriptions/${var.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/${value}" }
  existing_segments      = split("/", var.existing_foundry_project_resource_id)
  existing_account_scope = var.use_existing_ai_project ? join("/", slice(local.existing_segments, 0, 9)) : ""
  assignments = merge(
    !var.use_existing_ai_project ? {
      search_openai      = { scope = var.ai_foundry_resource_id, principal = var.ai_search_principal_id, role = local.role_ids.openai_user, type = "ServicePrincipal" }
      backend_ai         = { scope = var.ai_foundry_resource_id, principal = var.backend_app_service_principal_id, role = local.role_ids.azure_ai_user, type = "ServicePrincipal" }
      deployer_cognitive = { scope = var.ai_foundry_resource_id, principal = var.deployer_principal_id, role = local.role_ids.cognitive_services_user, type = var.deployer_principal_type }
      deployer_ai        = { scope = var.ai_foundry_resource_id, principal = var.deployer_principal_id, role = local.role_ids.azure_ai_user, type = var.deployer_principal_type }
    } : {},
    {
      project_search_reader       = { scope = var.ai_search_resource_id, principal = var.ai_project_principal_id, role = local.role_ids.search_reader, type = "ServicePrincipal" }
      project_search_contributor  = { scope = var.ai_search_resource_id, principal = var.ai_project_principal_id, role = local.role_ids.search_service_contributor, type = "ServicePrincipal" }
      backend_search_reader       = { scope = var.ai_search_resource_id, principal = var.backend_app_service_principal_id, role = local.role_ids.search_reader, type = "ServicePrincipal" }
      project_storage_contributor = { scope = var.storage_account_resource_id, principal = var.ai_project_principal_id, role = local.role_ids.storage_contributor, type = "ServicePrincipal" }
      project_storage_reader      = { scope = var.storage_account_resource_id, principal = var.ai_project_principal_id, role = local.role_ids.storage_reader, type = "ServicePrincipal" }
      search_storage_reader       = { scope = var.storage_account_resource_id, principal = var.ai_search_principal_id, role = local.role_ids.storage_reader, type = "ServicePrincipal" }
      deployer_search_index       = { scope = var.ai_search_resource_id, principal = var.deployer_principal_id, role = local.role_ids.search_contributor, type = var.deployer_principal_type }
      deployer_search_service     = { scope = var.ai_search_resource_id, principal = var.deployer_principal_id, role = local.role_ids.search_service_contributor, type = var.deployer_principal_type }
      deployer_storage            = { scope = var.storage_account_resource_id, principal = var.deployer_principal_id, role = local.role_ids.storage_contributor, type = var.deployer_principal_type }
      backend_acr                 = { scope = var.container_registry_resource_id, principal = var.backend_app_service_principal_id, role = local.role_ids.acr_pull, type = "ServicePrincipal" }
      frontend_acr                = { scope = var.container_registry_resource_id, principal = var.frontend_app_service_principal_id, role = local.role_ids.acr_pull, type = "ServicePrincipal" }
    }
  )
}
resource "azurerm_role_assignment" "main" {
  for_each           = local.assignments
  name               = uuidv5("url", "${var.solution_name}|${each.value.scope}|${each.value.principal}|${each.value.role}")
  scope              = each.value.scope
  role_definition_id = each.value.role
  principal_id       = each.value.principal
  principal_type     = each.value.type
}
resource "azapi_resource" "cosmos_role" {
  type                      = "Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2025-10-15"
  name                      = uuidv5("url", "${var.solution_name}|${var.cosmos_db_account_id}|${var.backend_app_service_principal_id}")
  parent_id                 = var.cosmos_db_account_id
  schema_validation_enabled = false
  body                      = { properties = { principalId = var.backend_app_service_principal_id, roleDefinitionId = "${var.cosmos_db_account_id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002", scope = var.cosmos_db_account_id } }
}
module "assign_openai_to_search_existing" {
  count                = var.use_existing_ai_project ? 1 : 0
  source               = "../cross-scope-role-assignment"
  subscription_id      = local.existing_segments[2]
  resource_group_name  = local.existing_segments[4]
  ai_foundry_name      = local.existing_segments[8]
  principal_id         = var.ai_search_principal_id
  role_definition_id   = local.role_ids.openai_user
  role_assignment_name = uuidv5("url", "${var.solution_name}|${local.existing_account_scope}|${var.ai_search_principal_id}|${local.role_ids.openai_user}")
}
module "backend_ai_user_existing" {
  count                = var.use_existing_ai_project ? 1 : 0
  source               = "../cross-scope-role-assignment"
  subscription_id      = local.existing_segments[2]
  resource_group_name  = local.existing_segments[4]
  ai_foundry_name      = local.existing_segments[8]
  principal_id         = var.backend_app_service_principal_id
  role_definition_id   = local.role_ids.azure_ai_user
  role_assignment_name = uuidv5("url", "${var.solution_name}|${local.existing_account_scope}|${var.backend_app_service_principal_id}|${local.role_ids.azure_ai_user}")
}
