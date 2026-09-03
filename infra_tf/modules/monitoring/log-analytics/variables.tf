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
variable "retention_in_days" {
  type    = number
  default = 365
}
variable "sku_name" {
  type    = string
  default = "PerGB2018"
}
variable "identity" {
  type = object({
  type = string })
  default = { type = "SystemAssigned" }
}
variable "resource_group_name" {
  type = string
}
