variable "solution_name" {
  type    = string
  default = ""
}
variable "use_existing_ai_project" {
  type    = bool
  default = false
}
variable "existing_foundry_project_resource_id" {
  type    = string
  default = ""
}
variable "ai_project_principal_id" {
  type    = string
  default = ""
}
variable "ai_search_principal_id" {
  type    = string
  default = ""
}
variable "backend_app_service_principal_id" {
  type    = string
  default = ""
}
variable "frontend_app_service_principal_id" {
  type    = string
  default = ""
}
variable "deployer_principal_id" {
  type    = string
  default = ""
}
variable "deployer_principal_type" {
  type    = string
  default = "User"
}
variable "ai_foundry_resource_id" {
  type    = string
  default = ""
}
variable "ai_search_resource_id" {
  type    = string
  default = ""
}
variable "storage_account_resource_id" {
  type    = string
  default = ""
}
variable "cosmos_db_account_name" {
  type    = string
  default = ""
}
variable "container_registry_resource_id" {
  type    = string
  default = ""
}
variable "cosmos_db_account_id" {
  type = string
}
variable "subscription_id" {
  type = string
}
variable "resource_group_name" {
  type = string
}
