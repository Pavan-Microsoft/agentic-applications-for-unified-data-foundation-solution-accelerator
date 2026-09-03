locals {
  location = coalesce(var.location, var.azure_ai_service_location)
  solution_unique_text = coalesce(
    var.solution_unique_text,
    substr(md5(join("-", [var.subscription_id, var.resource_group_name, var.solution_name])), 0, 5)
  )
  solution_suffix               = lower(replace(replace(replace(replace(replace(replace("${var.solution_name}${local.solution_unique_text}", "-", ""), "_", ""), ".", ""), "/", ""), " ", ""), "*", ""))
  container_registry_name       = var.container_registry_name != "" ? var.container_registry_name : substr("cr${local.solution_suffix}", 0, 50)
  use_existing_ai_project       = var.existing_foundry_project_resource_id != ""
  use_existing_log_analytics    = var.existing_log_analytics_workspace_id != ""
  create_fabric_workspace       = var.fabric_workspace_id == ""
  use_existing_fabric_capacity  = var.azure_fabric_capacity_name != ""
  should_create_fabric_capacity = local.create_fabric_workspace && !local.use_existing_fabric_capacity
  fabric_capacity_name          = local.use_existing_fabric_capacity ? var.azure_fabric_capacity_name : "fc${local.solution_suffix}"
  deployment_administrator      = var.deploying_user_principal_type == "User" && try(trimspace(var.deployment_user_upn), "") != "" ? var.deployment_user_upn : data.azurerm_client_config.current.object_id
  fabric_admin_members          = distinct(concat(local.deployment_administrator == null ? [] : [local.deployment_administrator], var.fabric_admin_members))
  created_by                    = var.deploying_user_principal_type == "User" && var.deployment_user_upn != null ? split("@", var.deployment_user_upn)[0] : data.azurerm_client_config.current.object_id
  resource_tags = merge(var.tags, {
    TemplateName = "Unified Data Analysis Agents"
    CreatedBy    = local.created_by
    Type         = "Non-WAF"
  })
  ai_foundry_segments       = split("/", var.existing_foundry_project_resource_id)
  ai_foundry_name           = local.use_existing_ai_project ? local.ai_foundry_segments[8] : module.ai_foundry_project[0].name
  ai_project_name           = local.use_existing_ai_project ? local.ai_foundry_segments[10] : module.ai_foundry_project[0].project_name
  ai_foundry_resource_group = local.use_existing_ai_project ? local.ai_foundry_segments[4] : var.resource_group_name
  ai_foundry_endpoint       = local.use_existing_ai_project ? module.existing_project_setup[0].endpoint : module.ai_foundry_project[0].endpoint
  project_endpoint          = local.use_existing_ai_project ? module.existing_project_setup[0].project_endpoint : module.ai_foundry_project[0].project_endpoint
  ai_foundry_resource_id    = local.use_existing_ai_project ? module.existing_project_setup[0].resource_id : module.ai_foundry_project[0].resource_id
  ai_project_principal_id   = local.use_existing_ai_project ? module.existing_project_setup[0].project_identity_principal_id : module.ai_foundry_project[0].project_identity_principal_id
  backend_app               = var.backend_runtime_stack == "python" ? module.backend_docker[0] : module.backend_csapi_docker[0]
  placeholder_image         = "DOCKER|mcr.microsoft.com/azuredocs/aci-helloworld:latest"
  common_backend_settings = {
    APPINSIGHTS_INSTRUMENTATIONKEY         = module.app_insights.instrumentation_key
    AZURE_ENV_GPT_MODEL_NAME               = var.gpt_model_name
    AZURE_ENV_EMBEDDING_DEPLOYMENT_NAME    = var.embedding_model
    AZURE_OPENAI_ENDPOINT                  = local.ai_foundry_endpoint
    AZURE_ENV_OPENAI_API_VERSION           = var.azure_openai_api_version
    AZURE_OPENAI_RESOURCE                  = local.ai_foundry_name
    AZURE_AI_AGENT_ENDPOINT                = local.project_endpoint
    AZURE_AI_AGENT_API_VERSION             = var.azure_ai_agent_api_version
    AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME   = var.gpt_model_name
    USE_CHAT_HISTORY_ENABLED               = var.use_chat_history_enabled ? "True" : "False"
    AZURE_COSMOSDB_ACCOUNT                 = module.cosmos_db.name
    AZURE_COSMOSDB_CONVERSATIONS_CONTAINER = module.cosmos_db.container_name
    AZURE_COSMOSDB_DATABASE                = module.cosmos_db.database_name
    AZURE_COSMOSDB_ENABLE_FEEDBACK         = "True"
    API_UID                                = ""
    AZURE_AI_SEARCH_ENDPOINT               = module.ai_search.endpoint
    AZURE_AI_SEARCH_INDEX                  = "knowledge_index"
    AZURE_AI_SEARCH_CONNECTION_NAME        = module.foundry_search_connection.connection_name
    USE_AI_PROJECT_CLIENT                  = "True"
    DISPLAY_CHART_DEFAULT                  = "False"
    APPLICATIONINSIGHTS_CONNECTION_STRING  = module.app_insights.connection_string
    DUMMY_TEST                             = "True"
    SOLUTION_NAME                          = local.solution_suffix
    USE_USER_ACCESS_TOKEN                  = var.use_user_access_token ? "True" : "False"
    APP_ENV                                = "Prod"
    AGENT_NAME_CHAT                        = ""
    AGENT_NAME_TITLE                       = ""
    FABRIC_SQL_DATABASE                    = ""
    FABRIC_SQL_SERVER                      = ""
    FABRIC_SQL_CONNECTION_STRING           = ""
  }
}

resource "azurerm_resource_group" "main" {
  name     = var.resource_group_name
  location = local.location
  tags     = local.resource_tags
}

module "fabric_capacity" {
  count               = local.should_create_fabric_capacity ? 1 : 0
  source              = "./modules/fabric/fabric-capacity"
  name                = local.fabric_capacity_name
  solution_name       = local.solution_suffix
  location            = local.location
  sku_name            = var.fabric_capacity_sku
  admin_members       = local.fabric_admin_members
  tags                = local.resource_tags
  resource_group_name = azurerm_resource_group.main.name
}

module "log_analytics" {
  count               = local.use_existing_log_analytics ? 0 : 1
  source              = "./modules/monitoring/log-analytics"
  solution_name       = local.solution_suffix
  location            = var.azure_ai_service_location
  resource_group_name = azurerm_resource_group.main.name
}

module "app_insights" {
  source                = "./modules/monitoring/app-insights"
  solution_name         = local.solution_suffix
  location              = var.azure_ai_service_location
  resource_group_name   = azurerm_resource_group.main.name
  workspace_resource_id = local.use_existing_log_analytics ? var.existing_log_analytics_workspace_id : module.log_analytics[0].resource_id
}

module "existing_project_setup" {
  count               = local.use_existing_ai_project ? 1 : 0
  source              = "./modules/ai/existing-project-setup"
  subscription_id     = var.subscription_id
  name                = local.ai_foundry_segments[8]
  project_name        = local.ai_foundry_segments[10]
  resource_group_name = local.ai_foundry_segments[4]
}

module "ai_foundry_project" {
  count               = local.use_existing_ai_project ? 0 : 1
  source              = "./modules/ai/ai-foundry-project"
  subscription_id     = var.subscription_id
  solution_name       = local.solution_suffix
  location            = var.azure_ai_service_location
  resource_group_name = azurerm_resource_group.main.name
}

module "ai_search" {
  source              = "./modules/ai/ai-search"
  subscription_id     = var.subscription_id
  solution_name       = local.solution_suffix
  location            = local.location
  resource_group_name = azurerm_resource_group.main.name
}

module "storage_account" {
  source              = "./modules/data/storage-account"
  solution_name       = local.solution_suffix
  location            = var.azure_ai_service_location
  resource_group_name = azurerm_resource_group.main.name
  containers          = [{ name = "default", public_access = "None" }]
}

module "cosmos_db" {
  source              = "./modules/data/cosmos-db-nosql"
  solution_name       = local.solution_suffix
  name                = "cosmos-${local.solution_suffix}"
  location            = local.location
  resource_group_name = azurerm_resource_group.main.name
  database_name       = "db_conversation_history"
  containers          = [{ name = "conversations", partition_key_path = "/userId" }]
}

module "app_service_plan" {
  source              = "./modules/compute/app-service-plan"
  solution_name       = local.solution_suffix
  location            = local.location
  resource_group_name = azurerm_resource_group.main.name
  sku_name            = var.app_service_plan_sku
}

module "container_registry" {
  source                = "./modules/compute/container-registry"
  solution_name         = local.solution_suffix
  name                  = local.container_registry_name
  location              = local.location
  resource_group_name   = azurerm_resource_group.main.name
  tags                  = var.tags
  sku                   = "Standard"
  public_network_access = "Enabled"
}

module "foundry_search_connection" {
  source                   = "./modules/ai/ai-foundry-connection"
  subscription_id          = var.subscription_id
  resource_group_name      = local.ai_foundry_resource_group
  ai_services_account_name = local.ai_foundry_name
  project_name             = local.ai_project_name
  solution_name            = local.solution_suffix
  category                 = "CognitiveSearch"
  target                   = module.ai_search.endpoint
  auth_type                = "AAD"
  metadata                 = { ApiType = "Azure", ResourceId = module.ai_search.resource_id }
}

module "foundry_storage_connection" {
  source                   = "./modules/ai/ai-foundry-connection"
  subscription_id          = var.subscription_id
  resource_group_name      = local.ai_foundry_resource_group
  ai_services_account_name = local.ai_foundry_name
  project_name             = local.ai_project_name
  solution_name            = local.solution_suffix
  category                 = "AzureBlob"
  target                   = module.storage_account.blob_endpoint
  auth_type                = "AAD"
  metadata                 = { ResourceId = module.storage_account.resource_id, AccountName = module.storage_account.name, ContainerName = "default" }
}

module "foundry_appi_connection" {
  count                    = local.use_existing_ai_project ? 0 : 1
  source                   = "./modules/ai/ai-foundry-connection"
  subscription_id          = var.subscription_id
  resource_group_name      = local.ai_foundry_resource_group
  ai_services_account_name = local.ai_foundry_name
  project_name             = local.ai_project_name
  solution_name            = local.solution_suffix
  category                 = "AppInsights"
  target                   = module.app_insights.resource_id
  auth_type                = "ApiKey"
  is_default               = true
  credentials_key          = module.app_insights.instrumentation_key
  metadata                 = { ApiType = "Azure", ResourceId = module.app_insights.resource_id }
}

module "gpt_model_deployment" {
  source                   = "./modules/ai/ai-foundry-model-deployment"
  subscription_id          = var.subscription_id
  resource_group_name      = local.ai_foundry_resource_group
  ai_services_account_name = local.ai_foundry_name
  deployment_name          = var.gpt_model_name
  model_name               = var.gpt_model_name
  model_version            = var.gpt_model_version
  sku_name                 = var.deployment_type
  sku_capacity             = var.gpt_deployment_capacity
  depends_on               = [module.ai_foundry_project]
}

module "embedding_model_deployment" {
  source                   = "./modules/ai/ai-foundry-model-deployment"
  subscription_id          = var.subscription_id
  resource_group_name      = local.ai_foundry_resource_group
  ai_services_account_name = local.ai_foundry_name
  deployment_name          = var.embedding_model
  model_name               = var.embedding_model
  model_version            = "1"
  sku_name                 = "GlobalStandard"
  sku_capacity             = var.embedding_deployment_capacity
  depends_on               = [module.gpt_model_deployment]
}

module "backend_docker" {
  count                          = var.backend_runtime_stack == "python" ? 1 : 0
  source                         = "./modules/compute/app-service"
  solution_name                  = local.solution_suffix
  name                           = "api-${local.solution_suffix}"
  location                       = local.location
  resource_group_name            = azurerm_resource_group.main.name
  server_farm_resource_id        = module.app_service_plan.resource_id
  linux_fx_version               = local.placeholder_image
  acr_use_managed_identity_creds = true
  cors_allowed_origins           = ["https://app-${local.solution_suffix}.azurewebsites.net"]
  app_settings                   = merge(local.common_backend_settings, { AZURE_SQLDB_USER_MID = "", AZURE_BASIC_LOGGING_LEVEL = "INFO", AZURE_PACKAGE_LOGGING_LEVEL = "WARNING", AZURE_LOGGING_PACKAGES = "" })
}

module "backend_csapi_docker" {
  count                          = var.backend_runtime_stack == "dotnet" ? 1 : 0
  source                         = "./modules/compute/app-service"
  solution_name                  = local.solution_suffix
  name                           = "api-cs-${local.solution_suffix}"
  location                       = local.location
  resource_group_name            = azurerm_resource_group.main.name
  server_farm_resource_id        = module.app_service_plan.resource_id
  linux_fx_version               = local.placeholder_image
  acr_use_managed_identity_creds = true
  cors_allowed_origins           = ["https://app-${local.solution_suffix}.azurewebsites.net"]
  app_settings                   = local.common_backend_settings
}

module "frontend_docker" {
  source                         = "./modules/compute/app-service"
  solution_name                  = local.solution_suffix
  name                           = "app-${local.solution_suffix}"
  location                       = local.location
  resource_group_name            = azurerm_resource_group.main.name
  server_farm_resource_id        = module.app_service_plan.resource_id
  linux_fx_version               = local.placeholder_image
  acr_use_managed_identity_creds = true
  app_settings = {
    APPINSIGHTS_INSTRUMENTATIONKEY = module.app_insights.instrumentation_key
    APP_API_BASE_URL               = local.backend_app.app_url
    CHAT_LANDING_TEXT              = ""
    APP_TITLE_PRIMARY              = var.app_title_primary
    APP_TITLE_SECONDARY            = var.app_title_secondary
  }
}

module "role_assignments" {
  source                               = "./modules/identity/role-assignments"
  solution_name                        = local.solution_suffix
  subscription_id                      = var.subscription_id
  resource_group_name                  = azurerm_resource_group.main.name
  use_existing_ai_project              = local.use_existing_ai_project
  existing_foundry_project_resource_id = var.existing_foundry_project_resource_id
  ai_project_principal_id              = local.ai_project_principal_id
  ai_search_principal_id               = module.ai_search.identity_principal_id
  backend_app_service_principal_id     = local.backend_app.identity_principal_id
  frontend_app_service_principal_id    = module.frontend_docker.identity_principal_id
  deployer_principal_id                = data.azurerm_client_config.current.object_id
  deployer_principal_type              = var.deploying_user_principal_type
  ai_foundry_resource_id               = local.use_existing_ai_project ? "" : local.ai_foundry_resource_id
  ai_search_resource_id                = module.ai_search.resource_id
  storage_account_resource_id          = module.storage_account.resource_id
  cosmos_db_account_name               = module.cosmos_db.name
  cosmos_db_account_id                 = module.cosmos_db.resource_id
  container_registry_resource_id       = module.container_registry.resource_id
}
