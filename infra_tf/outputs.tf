output "solution_name" {
  value = local.solution_suffix
}
output "resource_group_name" {
  value = azurerm_resource_group.main.name
}
output "deployment_flavor" {
  value = var.deployment_flavor
}
output "deployment_type" {
  value = "N/A"
}
output "azure_env_container_registry_name" {
  value = module.container_registry.name
}
output "azure_container_registry_endpoint" {
  value = module.container_registry.login_server
}
output "azure_env_image_tag" {
  value = var.image_tag
}
output "azure_cosmosdb_account" {
  value = module.cosmos_db.name
}
output "azure_cosmosdb_conversations_container" {
  value = module.cosmos_db.container_name
}
output "azure_cosmosdb_database" {
  value = module.cosmos_db.database_name
}
output "azure_env_gpt_model_name" {
  value = var.gpt_model_name
}
output "azure_openai_endpoint" {
  value = local.ai_foundry_endpoint
}
output "azure_env_embedding_deployment_name" {
  value = var.embedding_model
}
output "azure_sqldb_user_mid" {
  value = ""
}
output "api_uid" {
  value = ""
}
output "azure_ai_agent_endpoint" {
  value = local.project_endpoint
}
output "azure_ai_agent_model_deployment_name" {
  value = var.gpt_model_name
}
output "api_app_name" {
  value = local.backend_app.name
}
output "api_pid" {
  value = local.backend_app.identity_principal_id
}
output "mid_display_name" {
  value = local.backend_app.name
}
output "web_app_name" {
  value = module.frontend_docker.name
}
output "web_app_url" {
  value = module.frontend_docker.app_url
}
output "azure_ai_search_endpoint" {
  value = module.ai_search.endpoint
}
output "azure_ai_search_index" {
  value = "knowledge_index"
}
output "azure_ai_search_name" {
  value = module.ai_search.name
}
output "search_data_folder" {
  value = "data/default/documents"
}
output "azure_ai_search_connection_name" {
  value = module.foundry_search_connection.connection_name
}
output "azure_ai_search_connection_id" {
  value = module.foundry_search_connection.connection_id
}
output "azure_ai_project_endpoint" {
  value = local.project_endpoint
}
output "ai_foundry_resource_id" {
  value = local.ai_foundry_resource_id
}
output "azure_ai_project_name" {
  value = local.ai_project_name
}
output "ai_service_name" {
  value = local.ai_foundry_name
}
output "foundry_project_pid" {
  value = local.ai_project_principal_id
}
output "use_chat_history_enabled" {
  value = var.use_chat_history_enabled ? "True" : "False"
}
output "backend_runtime_stack" {
  value = var.backend_runtime_stack
}
output "use_user_access_token" {
  value = var.use_user_access_token ? "True" : "False"
}
output "azure_fabric_capacity_resource_id" {
  value = local.should_create_fabric_capacity ? module.fabric_capacity[0].resource_id : ""
}
output "azure_fabric_capacity_name" {
  value = local.create_fabric_workspace ? local.fabric_capacity_name : ""
}
output "fabric_admin_members" {
  value = local.should_create_fabric_capacity ? local.fabric_admin_members : []
}
output "create_fabric_workspace" {
  value = local.create_fabric_workspace
}
output "fabric_workspace_id" {
  value = var.fabric_workspace_id
}
