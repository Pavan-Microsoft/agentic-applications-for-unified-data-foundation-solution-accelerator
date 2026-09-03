terraform {
  required_version = ">= 1.6.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    azapi = {
      source  = "Azure/azapi"
      version = "~> 2.0"
    }
  }


}

provider "azurerm" {
  subscription_id = var.subscription_id
  features {}
  storage_use_azuread = true
}

provider "azapi" {}

data "azurerm_client_config" "current" {}
