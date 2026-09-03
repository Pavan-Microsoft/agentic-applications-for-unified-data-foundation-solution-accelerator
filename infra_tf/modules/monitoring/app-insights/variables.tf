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
variable "workspace_resource_id" {
  type = string
}
variable "application_type" {
  type    = string
  default = "web"
}
variable "retention_in_days" {
  type    = number
  default = 365
}
variable "disable_ip_masking" {
  type    = bool
  default = false
}
variable "flow_type" {
  type    = string
  default = "Bluefield"
}
variable "kind" {
  type    = string
  default = "web"
}
variable "resource_group_name" {
  type = string
}
