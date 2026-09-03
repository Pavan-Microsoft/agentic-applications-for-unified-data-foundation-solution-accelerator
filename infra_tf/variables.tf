variable "subscription_id" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "deployment_flavor" {
  type = string
  validation {
    condition     = var.deployment_flavor == "bicep"
    error_message = "This Terraform port implements the selected bicep flavor."
  }
}

variable "solution_name" {
  type    = string
  default = "agenticappudf"
  validation {
    condition     = length(var.solution_name) >= 3 && length(var.solution_name) <= 20
    error_message = "solution_name must contain between 3 and 20 characters."
  }
}

variable "solution_unique_text" {
  type     = string
  default  = null
  nullable = true
  validation {
    condition     = var.solution_unique_text == null || length(var.solution_unique_text) <= 5
    error_message = "solution_unique_text must contain at most 5 characters."
  }
}

variable "location" {
  type     = string
  default  = null
  nullable = true
}

variable "azure_ai_service_location" {
  type = string
  validation {
    condition     = contains(["australiaeast", "eastus", "eastus2", "francecentral", "japaneast", "swedencentral", "uksouth", "westus", "westus3"], var.azure_ai_service_location)
    error_message = "azure_ai_service_location must be a supported AI deployment region."
  }
}

variable "deployment_type" {
  type    = string
  default = "GlobalStandard"
  validation {
    condition     = contains(["Standard", "GlobalStandard"], var.deployment_type)
    error_message = "deployment_type must be Standard or GlobalStandard."
  }
}

variable "gpt_model_name" {
  type    = string
  default = "gpt-5.4-mini"
}
variable "gpt_model_version" {
  type    = string
  default = "2026-03-17"
}
variable "azure_openai_api_version" {
  type    = string
  default = "2025-01-01-preview"
}
variable "azure_ai_agent_api_version" {
  type    = string
  default = "2025-05-01"
}

variable "gpt_deployment_capacity" {
  type    = number
  default = 150
  validation {
    condition     = var.gpt_deployment_capacity >= 10
    error_message = "gpt_deployment_capacity must be at least 10."
  }
}

variable "embedding_model" {
  type    = string
  default = "text-embedding-3-small"
  validation {
    condition     = var.embedding_model == "text-embedding-3-small"
    error_message = "embedding_model must be text-embedding-3-small."
  }
}

variable "embedding_deployment_capacity" {
  type    = number
  default = 80
  validation {
    condition     = var.embedding_deployment_capacity >= 10
    error_message = "embedding_deployment_capacity must be at least 10."
  }
}

variable "image_tag" {
  type    = string
  default = "latest_v3"
}
variable "container_registry_name" {
  type    = string
  default = ""
}

variable "backend_runtime_stack" {
  type    = string
  default = "python"
  validation {
    condition     = contains(["python", "dotnet"], var.backend_runtime_stack)
    error_message = "backend_runtime_stack must be python or dotnet."
  }
}

variable "app_service_plan_sku" {
  type    = string
  default = "B2"
  validation {
    condition     = contains(["F1", "D1", "B1", "B2", "B3", "S1", "S2", "S3", "P1", "P2", "P3", "P1v3", "P1v4"], var.app_service_plan_sku)
    error_message = "app_service_plan_sku is not supported by the source contract."
  }
}

variable "use_chat_history_enabled" {
  type    = bool
  default = true
}
variable "use_user_access_token" {
  type    = bool
  default = true
}
variable "existing_log_analytics_workspace_id" {
  type    = string
  default = ""
}
variable "existing_foundry_project_resource_id" {
  type    = string
  default = ""
}

variable "deploying_user_principal_type" {
  type    = string
  default = "User"
  validation {
    condition     = contains(["User", "ServicePrincipal"], var.deploying_user_principal_type)
    error_message = "deploying_user_principal_type must be User or ServicePrincipal."
  }
}

variable "deployment_user_upn" {
  type     = string
  default  = null
  nullable = true
}

variable "app_title_primary" {
  type    = string
  default = "Contoso"
}
variable "app_title_secondary" {
  type    = string
  default = "| Unified Data Analysis Agents"
}
variable "tags" {
  type    = map(string)
  default = {}
}
variable "enable_telemetry" {
  type    = bool
  default = true
}
variable "enable_monitoring" {
  type    = bool
  default = false
}
variable "enable_private_networking" {
  type    = bool
  default = false
}
variable "enable_scalability" {
  type    = bool
  default = false
}
variable "enable_redundancy" {
  type    = bool
  default = false
}
variable "fabric_workspace_id" {
  type    = string
  default = ""
}
variable "azure_fabric_capacity_name" {
  type    = string
  default = ""
}

variable "fabric_capacity_sku" {
  type    = string
  default = "F2"
  validation {
    condition     = contains(["F2", "F4", "F8", "F16", "F32", "F64", "F128", "F256", "F512", "F1024", "F2048"], var.fabric_capacity_sku)
    error_message = "fabric_capacity_sku is not supported by the source contract."
  }
}

variable "fabric_admin_members" {
  type    = list(string)
  default = []
}
variable "vm_admin_username" {
  type      = string
  default   = null
  nullable  = true
  sensitive = true
}

variable "vm_admin_password" {
  type      = string
  default   = null
  nullable  = true
  sensitive = true
}
variable "vm_size" {
  type    = string
  default = "Standard_D2s_v5"
}
