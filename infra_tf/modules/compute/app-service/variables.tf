variable "solution_name" {
  type = string
}
variable "name" {
  type    = string
  default = null
}
variable "location" {
  type = string
}
variable "tags" {
  type    = map(string)
  default = {}
}
variable "server_farm_resource_id" {
  type = string
}
variable "linux_fx_version" {
  type = string
}
variable "app_settings" {
  type    = map(string)
  default = {}
}
variable "always_on" {
  type    = bool
  default = true
}
variable "health_check_path" {
  type    = string
  default = ""
}
variable "web_sockets_enabled" {
  type    = bool
  default = false
}
variable "app_command_line" {
  type    = string
  default = ""
}
variable "cors_allowed_origins" {
  type    = list(string)
  default = []
}
variable "kind" {
  type    = string
  default = "app,linux"
}
variable "public_network_access" {
  type    = string
  default = "Enabled"
}
variable "identity" {
  type = object({
  type = string })
  default = { type = "SystemAssigned" }
}
variable "acr_use_managed_identity_creds" {
  type    = bool
  default = false
}
variable "resource_group_name" {
  type = string
}
