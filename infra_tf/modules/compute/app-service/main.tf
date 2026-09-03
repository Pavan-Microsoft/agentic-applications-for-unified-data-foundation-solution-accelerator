locals {
  name         = coalesce(var.name, var.solution_name)
  docker_image = replace(var.linux_fx_version, "DOCKER|", "")
}
resource "azurerm_linux_web_app" "main" {
  name                                           = local.name
  resource_group_name                            = var.resource_group_name
  location                                       = var.location
  service_plan_id                                = var.server_farm_resource_id
  tags                                           = var.tags
  public_network_access_enabled                  = var.public_network_access == "Enabled"
  https_only                                     = true
  app_settings                                   = var.app_settings
  ftp_publish_basic_authentication_enabled       = false
  webdeploy_publish_basic_authentication_enabled = false
  identity { type = var.identity.type }
  site_config {
    always_on                               = var.always_on
    ftps_state                              = "Disabled"
    minimum_tls_version                     = "1.2"
    health_check_path                       = var.health_check_path != "" ? var.health_check_path : null
    websockets_enabled                      = var.web_sockets_enabled
    app_command_line                        = var.app_command_line
    container_registry_use_managed_identity = var.acr_use_managed_identity_creds
    application_stack { docker_image_name = local.docker_image }
    dynamic "cors" {
      for_each = length(var.cors_allowed_origins) > 0 ? [1] : []
      content { allowed_origins = var.cors_allowed_origins }
    }
  }
  logs {
    detailed_error_messages = true
    failed_request_tracing  = true
    application_logs { file_system_level = "Verbose" }
    http_logs {
      file_system {
        retention_in_days = 1
        retention_in_mb   = 35
      }
    }
  }
}
