output "lambda_function_arn" {
  description = "ARN of the Vanta S3 CRR reconciler Lambda."
  value       = module.lambda.lambda_function_arn
}

output "lambda_function_name" {
  description = "Name of the Vanta S3 CRR reconciler Lambda."
  value       = module.lambda.lambda_function_name
}
