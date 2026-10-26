variable "pbs_storage_password" {
  description = "Existing PBS connection credential, supplied through the protected local environment when PBS is managed."
  type        = string
  sensitive   = true
  default     = null
}
