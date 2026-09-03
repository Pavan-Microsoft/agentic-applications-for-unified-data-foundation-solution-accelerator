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
variable "sku_name" {
  type    = string
  default = "basic"
}
variable "replica_count" {
  type    = number
  default = 1
}
variable "partition_count" {
  type    = number
  default = 1
}
variable "hosting_mode" {
  type    = string
  default = "Default"
}
variable "semantic_search" {
  type    = string
  default = "free"
}
variable "disable_local_auth" {
  type    = bool
  default = true
}
variable "auth_options" {
  type    = any
  default = {}
}
variable "network_rule_set" {
  type    = any
  default = {}
}
variable "identity" {
  type = object({
  type = string })
  default = { type = "SystemAssigned" }
}
variable "public_network_access" {
  type    = string
  default = "Enabled"
}
variable "resource_group_name" {
  type = string
}
variable "subscription_id" {
  type = string
}
