variable "principal_id" {
  type = string
}
variable "role_definition_id" {
  type = string
}
variable "role_assignment_name" {
  type = string
}
variable "ai_foundry_name" {
  type = string
}
variable "principal_type" {
  type    = string
  default = "ServicePrincipal"
}
variable "subscription_id" {
  type = string
}
variable "resource_group_name" {
  type = string
}
