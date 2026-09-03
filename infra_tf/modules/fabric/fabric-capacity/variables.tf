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
  default = "F2"
}
variable "admin_members" {
  type = list(string)
}
variable "resource_group_name" {
  type = string
}
