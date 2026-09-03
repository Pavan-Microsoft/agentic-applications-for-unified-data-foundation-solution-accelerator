variable "ai_services_account_name" {
  type = string
}
variable "project_name" {
  type = string
}
variable "solution_name" {
  type = string
}
variable "connection_name" {
  type    = string
  default = null
}
variable "category" {
  type = string
}
variable "target" {
  type = string
}
variable "auth_type" {
  type = string
}
variable "is_shared_to_all" {
  type    = bool
  default = true
}
variable "is_default" {
  type    = bool
  default = false
}
variable "metadata" {
  type    = map(string)
  default = {}
}
variable "use_workspace_managed_identity" {
  type    = bool
  default = false
}
variable "credentials_key" {
  type      = string
  default   = ""
  sensitive = true
}
variable "resource_group_name" {
  type = string
}
variable "subscription_id" {
  type    = string
  default = null
}
