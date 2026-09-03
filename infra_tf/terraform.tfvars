deployment_flavor = "bicep"
resource_group_name = ""
subscription_id     = ""
azure_ai_service_location = ""
deployment_user_upn = ""
# Required runtime values are supplied through TF_VAR_* by local tooling or CI:
# subscription_id, resource_group_name, solution_name, location,
# azure_ai_service_location, and any selected deployment/model settings.