variable "ai_services_account_name" {
  type = string
}
variable "deployment_name" {
  type = string
}
variable "model_format" {
  type    = string
  default = "OpenAI"
}
variable "model_name" {
  type = string
}
variable "model_version" {
  type    = string
  default = ""
}
variable "rai_policy_name" {
  type    = string
  default = "Microsoft.Default"
}
variable "sku_name" {
  type = string
}
variable "sku_capacity" {
  type = number
}
variable "resource_group_name" {
  type = string
}
variable "subscription_id" {
  type    = string
  default = null
}
