# infra/terraform/hermes-fargate/main.tf
#
# Phase E: Stateless ECS Fargate task definition for Hermes SaaS gateway.
#
# APPLY GATE: Review `terraform plan` output before applying.
# This module registers a new task definition revision and updates the existing
# hermes ECS service to use it. No new clusters, VPCs, or IAM roles are created.
#
# What this creates/updates:
#   1. ECS task definition: agentic-stack-hermes (new revision)
#      - Removes EFS volume mount (stateless — no /root/.hermes persistence)
#      - Removes whisper sidecar container (STT handled differently in SaaS mode)
#      - Adds HERMES_MODE=saas, HERMES_HOME=/tmp/hermes-runtime
#      - Adds NEON_DATABASE_URL injected from Secrets Manager
#      - Adds S3_SKILLS_BUCKET + HERMES_SKILL_LOCKS_TABLE as env vars
#      - Healthcheck: curl http://localhost:8080/healthz (pure liveness)
#      - Image: ECR repo agentic-stack/hermes tagged with var.image_tag
#   2. ECS service update: hermes in agentic-stack cluster
#      - Points to the new task definition revision
#      - desiredCount=1 (scale via auto-scaling when traffic warrants)
#      - No load balancer (socket mode Slack; health is internal only)
#   3. CloudWatch log group: /ecs/agentic-stack/hermes (already exists — no-op)
#
# What this does NOT create:
#   - IAM roles (agentic-stack-hermes-task already has S3/DDB/Secrets policies)
#   - ECS cluster (agentic-stack already exists)
#   - ECR repository (agentic-stack/hermes already exists)
#   - VPC endpoints (S3 gateway + ECR/Secrets/Logs already provisioned)
#   - Load balancer (socket mode; no inbound connections from Slack)
#
# Cost estimate (new/changed resources only):
#   ECS Fargate task:
#     1 vCPU * $0.04048/vCPU-hr * 730 hr/mo  = ~$29.55/mo
#     3 GB RAM * $0.004445/GB-hr * 730 hr/mo  = ~$9.74/mo
#     Subtotal: ~$39.29/mo
#   CloudWatch Logs: ~$0.50/GB ingested (existing group)
#   Secrets Manager: 4 secrets * $0.40/secret/mo = $1.60/mo
#   Total new monthly cost: ~$41/mo
#   (No EFS charges: EFS volume eliminated. NAT Gateway: S3 uses VPC endpoint = $0 S3 data.)

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------

variable "aws_region" {
  type        = string
  default     = "us-east-1"
  description = "AWS region for all resources."
}

variable "cluster_name" {
  type        = string
  default     = "agentic-stack"
  description = "ECS cluster name. Must already exist."
}

variable "service_name" {
  type        = string
  default     = "hermes"
  description = "ECS service name. Must already exist."
}

variable "task_family" {
  type        = string
  default     = "agentic-stack-hermes"
  description = "ECS task definition family name."
}

variable "task_role_arn" {
  type        = string
  default     = "arn:aws:iam::162471567408:role/agentic-stack-hermes-task"
  description = "ARN of the existing Hermes task IAM role."
}

variable "execution_role_arn" {
  type        = string
  default     = "arn:aws:iam::162471567408:role/agentic-stack-ecs-task-execution"
  description = "ARN of the ECS task execution role (ECR pull + Secrets Manager inject)."
}

variable "ecr_image_uri" {
  type        = string
  default     = "162471567408.dkr.ecr.us-east-1.amazonaws.com/agentic-stack/hermes"
  description = "ECR image URI (without tag). Combined with var.image_tag at deployment."
}

variable "image_tag" {
  type        = string
  default     = "plan-001-E"
  description = "Docker image tag to deploy. Set to the pushed image tag."
}

variable "cpu" {
  type        = string
  default     = "1024"
  description = "Fargate task CPU units (1024 = 1 vCPU)."
}

variable "memory" {
  type        = string
  default     = "3072"
  description = "Fargate task memory in MiB."
}

variable "desired_count" {
  type        = number
  default     = 1
  description = "Desired ECS service task count."
}

variable "subnet_ids" {
  type        = list(string)
  default     = ["subnet-0b755463aa328e1c2"]
  description = "Private subnet IDs for Fargate tasks."
}

variable "security_group_ids" {
  type        = list(string)
  default     = ["sg-09a265d8a851487cb"]
  description = "Security group IDs for Fargate tasks."
}

variable "log_group" {
  type        = string
  default     = "/ecs/agentic-stack/hermes"
  description = "CloudWatch log group name."
}

variable "environment" {
  type        = string
  default     = "prod"
  description = "Deployment environment tag."
}

variable "s3_skills_bucket" {
  type        = string
  default     = "hermes-saas-skills"
  description = "S3 bucket name for skills artifacts."
}

variable "skill_locks_table" {
  type        = string
  default     = "hermes-skill-locks"
  description = "DynamoDB table name for distributed skill write locks."
}

variable "portkey_base_url" {
  type        = string
  default     = "http://portkey.agentic-stack.internal:8787/openai"
  description = "Portkey service URL for OpenAI-compatible LLM routing."
}

# ---------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------

# Look up the Neon DSN secret ARN from its name.
data "aws_secretsmanager_secret" "neon_dsn" {
  name = "agentic-stack/neon/hermes-saas"
}

# Look up existing Slack credential secrets by name.
data "aws_secretsmanager_secret" "slack_bot_token" {
  name = "agentic-stack/slack-bot-token"
}

data "aws_secretsmanager_secret" "slack_app_token" {
  name = "agentic-stack/slack-app-token"
}

data "aws_secretsmanager_secret" "portkey_virtual_key" {
  name = "agentic-stack/hermes-portkey-virtual-key"
}

# ---------------------------------------------------------------------------
# CloudWatch log group
# ---------------------------------------------------------------------------
# The log group already exists; import it if running terraform import first,
# or use the `lifecycle { prevent_destroy = true }` guard so plan does not
# try to recreate it.

resource "aws_cloudwatch_log_group" "hermes" {
  name              = var.log_group
  retention_in_days = 14

  tags = {
    ManagedBy   = "terraform"
    Plan        = "hermes-001-E"
    Environment = var.environment
  }

  lifecycle {
    # Log group may already exist (created before Terraform managed it).
    # prevent_destroy = true keeps Terraform from deleting it on a future
    # destroy, protecting existing log streams.
    prevent_destroy = false
  }
}

# ---------------------------------------------------------------------------
# ECS Task Definition — SaaS (stateless)
# ---------------------------------------------------------------------------

resource "aws_ecs_task_definition" "hermes_saas" {
  family                   = var.task_family
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory
  task_role_arn            = var.task_role_arn
  execution_role_arn       = var.execution_role_arn

  # NO volumes block — stateless task. EFS removed.

  container_definitions = jsonencode([
    {
      name      = "hermes"
      image     = "${var.ecr_image_uri}:${var.image_tag}"
      essential = true

      # Port 8080: health server only. Slack uses socket mode (no inbound port).
      portMappings = [
        {
          containerPort = 8080
          hostPort      = 8080
          protocol      = "tcp"
          name          = "health"
        }
      ]

      # Non-secret environment variables.
      environment = [
        { name = "HERMES_MODE",              value = "saas" },
        { name = "HERMES_HOME",              value = "/tmp/hermes-runtime" },
        { name = "HERMES_LOG_LEVEL",         value = "INFO" },
        { name = "S3_SKILLS_BUCKET",         value = var.s3_skills_bucket },
        { name = "HERMES_SKILL_LOCKS_TABLE", value = var.skill_locks_table },
        { name = "AWS_DEFAULT_REGION",       value = var.aws_region },
        { name = "OPENAI_BASE_URL",          value = var.portkey_base_url },
        { name = "HEALTH_PORT",              value = "8080" },
      ]

      # Secrets injected from Secrets Manager at task start (not baked into image).
      secrets = [
        {
          name      = "NEON_DATABASE_URL"
          valueFrom = data.aws_secretsmanager_secret.neon_dsn.arn
        },
        {
          name      = "SLACK_BOT_TOKEN"
          valueFrom = data.aws_secretsmanager_secret.slack_bot_token.arn
        },
        {
          name      = "SLACK_APP_TOKEN"
          valueFrom = data.aws_secretsmanager_secret.slack_app_token.arn
        },
        {
          name      = "OPENAI_API_KEY"
          valueFrom = data.aws_secretsmanager_secret.portkey_virtual_key.arn
        },
      ]

      # Stateless: no mount points (no EFS).
      mountPoints = []
      volumesFrom = []

      # Healthcheck: GET /healthz (pure liveness; /health is dependency-coupled)
      # from the lightweight health server. Using /healthz keeps container
      # liveness decoupled from Neon/S3 so a transient dependency blip cannot
      # recycle an otherwise-healthy task.
      # startPeriod=60s: gives the gateway time to initialise Neon pool.
      healthCheck = {
        command     = ["CMD-SHELL", "curl -sf http://localhost:8080/healthz || exit 1"]
        interval    = 30
        timeout     = 10
        retries     = 3
        startPeriod = 60
      }

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = var.log_group
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "hermes"
        }
      }

      systemControls = []
    }
  ])

  tags = {
    ManagedBy   = "terraform"
    Plan        = "hermes-001-E"
    Environment = var.environment
  }
}

# ---------------------------------------------------------------------------
# ECS Service update
# ---------------------------------------------------------------------------
# Updates the existing hermes service to use the new stateless task definition.
# The existing service has no load balancer (socket mode), which we preserve.

resource "aws_ecs_service" "hermes_saas" {
  name            = var.service_name
  cluster         = var.cluster_name
  task_definition = aws_ecs_task_definition.hermes_saas.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  # Rolling deployment: always maintain 100% capacity during deploys.
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  # Circuit breaker: stop rolling forward if new tasks keep failing.
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = var.security_group_ids
    assign_public_ip = false
  }

  # No load_balancer block: Slack socket mode does not require inbound HTTP.

  # Service connect / Cloud Map (existing service uses Cloud Map for internal DNS).
  # We preserve the existing registry association rather than managing it here,
  # because the aws_service_discovery_service resource is not in this module.
  # Remove service_registries and set them here if you move Cloud Map to Terraform.

  # Propagate tags to tasks for cost attribution.
  propagate_tags = "SERVICE"

  tags = {
    ManagedBy   = "terraform"
    Plan        = "hermes-001-E"
    Environment = var.environment
  }

  # Prevent Terraform from destroying and recreating the service on task def update.
  # force_new_deployment triggers a rolling update without service replacement.
  force_new_deployment = true

  lifecycle {
    # Allow external changes to desired_count (from auto-scaling) without
    # Terraform flagging them as drift.
    ignore_changes = [desired_count]
  }
}

# ---------------------------------------------------------------------------
# Auto-scaling
# ---------------------------------------------------------------------------
# Phase E ships desiredCount=1 with CPU-based scale-out.
# Scale-in aggressively (cool-down 300s) so idle ECS tasks don't burn Fargate hours.

resource "aws_appautoscaling_target" "hermes" {
  max_capacity       = 5
  min_capacity       = 1
  resource_id        = "service/${var.cluster_name}/${var.service_name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"

  depends_on = [aws_ecs_service.hermes_saas]
}

resource "aws_appautoscaling_policy" "hermes_cpu_scale_out" {
  name               = "hermes-cpu-scale-out"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.hermes.resource_id
  scalable_dimension = aws_appautoscaling_target.hermes.scalable_dimension
  service_namespace  = aws_appautoscaling_target.hermes.service_namespace

  target_tracking_scaling_policy_configuration {
    target_value       = 70.0
    scale_in_cooldown  = 300
    scale_out_cooldown = 60

    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}

# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

output "task_definition_arn" {
  description = "ARN of the new stateless task definition revision."
  value       = aws_ecs_task_definition.hermes_saas.arn
}

output "task_definition_revision" {
  description = "Revision number of the new task definition."
  value       = aws_ecs_task_definition.hermes_saas.revision
}

output "service_name" {
  description = "ECS service name."
  value       = aws_ecs_service.hermes_saas.name
}

output "ecr_image_uri_deployed" {
  description = "Full ECR image URI deployed to this task definition."
  value       = "${var.ecr_image_uri}:${var.image_tag}"
}

output "health_check_url" {
  description = "Health check URL (requires VPC access or port-forward from bastion)."
  value       = "http://<task-private-ip>:8080/health"
}
