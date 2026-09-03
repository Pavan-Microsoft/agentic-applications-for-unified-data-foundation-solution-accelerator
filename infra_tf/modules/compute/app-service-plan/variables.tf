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
  default = "B2"
}
variable "reserved" {
  type    = bool
  default = true
}
variable "kind" {
  type    = string
  default = "linux"
}
variable "sku_capacity" {
  type    = number
  default = 1
}
variable "zone_redundant" {
  type    = bool
  default = false
}
variable "identity" {
  type = object({
  type = string })
  default = { type = "SystemAssigned" }
}
variable "resource_group_name" {
  type = string
}
